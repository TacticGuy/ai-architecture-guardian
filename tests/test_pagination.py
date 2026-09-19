from __future__ import annotations
from src.scraper.checkpoint import CheckpointStore
from src.scraper.pr_scraper import PullRequestScraper
from src.storage.jsonl import iter_jsonl
from tests.conftest import page, pr_node, settings


class FakeClient:
    def __init__(self, responses): self.responses = iter(responses); self.calls = []
    def execute(self, query, variables): self.calls.append(variables); return next(self.responses)


def test_multiple_pages_are_streamed_and_checkpointed(tmp_path):
    client = FakeClient([page([pr_node(1)], True, "cursor-1"), page([pr_node(2)])])
    scraper = PullRequestScraper(client, settings(), str(tmp_path / "raw.jsonl"), CheckpointStore(tmp_path / "checkpoint.json"))
    result = scraper.scrape_repository({"owner": "org", "name": "repo"})
    assert result["retrieved"] == 2 and result["completed"]
    assert [r["pr_number"] for r in iter_jsonl(tmp_path / "raw.jsonl")] == [1, 2]
    assert client.calls[1]["cursor"] == "cursor-1"
    assert CheckpointStore(tmp_path / "checkpoint.json").get("org/repo")["completed"] is True


def test_no_results_completes_repository(tmp_path):
    scraper = PullRequestScraper(FakeClient([page([])]), settings(), str(tmp_path / "raw.jsonl"), CheckpointStore(tmp_path / "checkpoint.json"))
    assert scraper.scrape_repository({"owner": "org", "name": "empty"})["completed"] is True

