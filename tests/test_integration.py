from __future__ import annotations

from src.filtering.pipeline import FilterStatistics, write_filter_outputs
from src.scraper.checkpoint import CheckpointStore
from src.scraper.pr_scraper import PullRequestScraper
from src.storage.jsonl import iter_jsonl
from tests.conftest import page, pr_node, settings


class FakeClient:
    def __init__(self, response): self.response = response
    def execute(self, query, variables): return self.response


def test_fake_graphql_scrape_then_filter_keeps_expected_prs(tmp_path):
    nodes = [
        pr_node(1, "Refactor subsystem", 3),
        pr_node(2, "Fix typo", 3),
        pr_node(3, "Architecture cleanup", 2),
        pr_node(4, "Decouple services", 5),
        pr_node(5, "Plain fix", 5),
        pr_node(6, "Refactor parser", 3),
        pr_node(7, "Tests", 1),
        pr_node(8, "Architecture update", 8),
        pr_node(9, "Formatting", 3),
        pr_node(10, "Decouple cache", 4),
    ]
    raw = tmp_path / "raw.jsonl"
    scraper = PullRequestScraper(FakeClient(page(nodes)), settings(), str(raw), CheckpointStore(tmp_path / "checkpoint.json"))
    scraper.scrape_repository({"owner": "org", "name": "repo"})
    stats = FilterStatistics()
    accepted = write_filter_outputs(iter_jsonl(raw), tmp_path / "filtered.jsonl", tmp_path / "audit.jsonl", 3,
                                    ["refactor", "architecture", "decouple"], stats)
    # Fake commits contain "Refactor internals", so all eight PRs passing impact survive semantic matching.
    assert accepted == 8
    assert stats.total_raw_prs == 10
    assert len(list(iter_jsonl(tmp_path / "audit.jsonl"))) == 10
