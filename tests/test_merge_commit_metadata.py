from __future__ import annotations

from src.github.queries import PULL_REQUESTS_QUERY
from src.scraper.checkpoint import CheckpointStore
from src.scraper.pr_scraper import PullRequestScraper
from src.storage.jsonl import iter_jsonl
from tests.conftest import page, pr_node, settings


class FakeClient:
    def __init__(self, response):
        self.response = response

    def execute(self, query, variables):
        return self.response


def test_query_requests_merge_commit_oid():
    assert "mergeCommit { oid }" in PULL_REQUESTS_QUERY


def test_scraper_saves_merge_commit_sha(tmp_path):
    node = pr_node(42)
    node["mergeCommit"] = {"oid": "abc123def456"}
    output = tmp_path / "raw.jsonl"
    scraper = PullRequestScraper(
        FakeClient(page([node])),
        settings(),
        str(output),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    scraper.scrape_repository({"owner": "org", "name": "repo"})

    [record] = list(iter_jsonl(output))
    assert record["merge_commit_sha"] == "abc123def456"


def test_missing_merge_commit_is_saved_as_none(tmp_path):
    output = tmp_path / "raw.jsonl"
    scraper = PullRequestScraper(
        FakeClient(page([pr_node(43)])),
        settings(),
        str(output),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    scraper.scrape_repository({"owner": "org", "name": "repo"})

    [record] = list(iter_jsonl(output))
    assert record["merge_commit_sha"] is None
