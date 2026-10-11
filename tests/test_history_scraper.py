from __future__ import annotations

import json

import pytest

from scripts.scrape_prs import arguments
from src.dataset.label_protocol import validate_coverage
from src.github.client import GitHubClientError
from src.github.queries import PULL_REQUESTS_HISTORY_QUERY
from src.scraper.pr_scraper import PullRequestScraper
from src.storage.jsonl import iter_jsonl
from tests.conftest import page, pr_node, settings


START = "2024-01-01T00:00:00Z"
END = "2024-12-31T23:59:59Z"
REPO = {"owner": "org", "name": "repo"}


def node(number, created, merged):
    return {**pr_node(number), "createdAt": created, "mergedAt": merged,
            "mergeCommit": {"oid": f"{number:040x}"}, "baseRefName": "main"}


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, query, variables):
        self.calls.append((query, variables))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def scraper(tmp_path, responses):
    client = FakeClient(responses)
    result = PullRequestScraper(client, settings(), str(tmp_path / "raw.jsonl"), None)
    return result, client, tmp_path / "coverage.json"


def test_includes_pr_opened_before_window_and_filters_by_merge_date(tmp_path):
    early = node(1, "2019-01-01T00:00:00Z", "2024-05-01T00:00:00Z")
    outside = node(2, "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z")
    later = node(3, "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z")
    obj, client, coverage = scraper(tmp_path, [page([early, outside], True, "next"), page([later])])
    summary = obj.scrape_window(REPO, START, END, coverage)
    rows = list(iter_jsonl(tmp_path / "raw.jsonl"))
    assert summary["completed"] and summary["window_prs"] == 2
    assert [row["pr_number"] for row in rows] == [1, 3]
    assert rows[0]["merge_commit_sha"] == f"{1:040x}"
    assert rows[0]["base_ref_name"] == "main"
    assert client.calls[0][0] == PULL_REQUESTS_HISTORY_QUERY
    assert client.calls[1][1]["cursor"] == "next"
    manifest = json.loads(coverage.read_text(encoding="utf-8"))
    assert manifest["repositories"][0]["completion_reason"] == "connection_exhausted"
    assert "org/repo" in validate_coverage(manifest, rows)


def test_boundary_after_window_end_certifies_window_without_traversing_newer_prs(tmp_path):
    within = node(1, "2024-01-01T00:00:00Z", "2024-05-01T00:00:00Z")
    newer = node(2, "2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z")
    obj, _, coverage = scraper(tmp_path, [page([within, newer], True, "more-newer-prs")])
    result = obj.scrape_window(REPO, START, END, coverage)
    assert result["completed"] and result["window_prs"] == 1
    state = json.loads(coverage.read_text(encoding="utf-8"))["repositories"][0]
    assert state["completion_reason"] == "created_after_window_end"


def test_page_limit_is_incomplete_and_resume_does_not_duplicate_rows(tmp_path):
    first = node(1, "2024-01-01T00:00:00Z", "2024-05-01T00:00:00Z")
    second = node(2, "2024-02-01T00:00:00Z", "2024-06-01T00:00:00Z")
    obj, _, coverage = scraper(tmp_path, [page([first], True, "next")])
    assert not obj.scrape_window(REPO, START, END, coverage, max_pages=1)["completed"]
    partial = json.loads(coverage.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="incomplete"):
        validate_coverage(partial, list(iter_jsonl(tmp_path / "raw.jsonl")))
    resumed, client, _ = scraper(tmp_path, [page([second])])
    result = resumed.scrape_window(REPO, START, END, coverage)
    assert client.calls[0][1]["cursor"] == "next"
    assert result["completed"] and result["window_prs"] == 2
    assert len(list(iter_jsonl(tmp_path / "raw.jsonl"))) == 2
    # Completed runs perform no requests and verify their persisted raw IDs.
    completed, client, _ = scraper(tmp_path, [])
    assert completed.scrape_window(REPO, START, END, coverage)["completed"]
    assert client.calls == []


def test_request_failure_preserves_incomplete_checkpoint_for_resume(tmp_path):
    first = node(1, "2024-01-01T00:00:00Z", "2024-05-01T00:00:00Z")
    obj, _, coverage = scraper(tmp_path, [page([first], True, "next"), GitHubClientError("offline")])
    with pytest.raises(GitHubClientError, match="offline"):
        obj.scrape_window(REPO, START, END, coverage)
    state = json.loads(coverage.read_text(encoding="utf-8"))["repositories"][0]
    assert state["pagination_completed"] is False
    assert state["cursor"] == "next" and state["collected_pr_ids"] == ["org/repo#1"]


@pytest.mark.parametrize("bad_page", [
    {"repository": {"pullRequests": {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "x"}}}},
    page([None]),
    page([node(1, "2024-01-01T00:00:00", "2024-05-01T00:00:00Z")]),
    page([node(1, "2024-02-01T00:00:00Z", "2024-05-01T00:00:00Z"),
          node(2, "2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z")]),
])
def test_malformed_pages_cannot_certify_coverage(tmp_path, bad_page):
    obj, _, coverage = scraper(tmp_path, [bad_page])
    with pytest.raises(RuntimeError):
        obj.scrape_window(REPO, START, END, coverage)
    assert json.loads(coverage.read_text(encoding="utf-8"))["repositories"][0]["pagination_completed"] is False


def test_replaying_raw_write_after_interruption_is_deduplicated(tmp_path):
    item = node(1, "2024-01-01T00:00:00Z", "2024-05-01T00:00:00Z")
    obj, _, coverage = scraper(tmp_path, [page([item])])
    # Simulate a raw append that completed before its coverage checkpoint.
    obj.writer.append(obj._normalize(item, "org", "repo"))
    result = obj.scrape_window(REPO, START, END, coverage)
    assert result["written"] == 0 and result["completed"]
    assert len(list(iter_jsonl(tmp_path / "raw.jsonl"))) == 1


def test_history_cli_rejects_ambiguous_limits_and_partial_date_arguments():
    with pytest.raises(SystemExit):
        arguments(["--repo", "org/repo", "--window-start", START])
    with pytest.raises(SystemExit):
        arguments(["--repo", "org/repo", "--window-start", START, "--window-end", END, "--max-prs", "10"])
    args = arguments(["--repo", "org/repo", "--window-start", START, "--window-end", END, "--max-pages", "1"])
    assert args.max_pages == 1
