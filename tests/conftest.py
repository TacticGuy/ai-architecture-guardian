from __future__ import annotations
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def settings() -> dict:
    return {"graphql_endpoint": "https://api.github.test/graphql", "request_timeout_seconds": 1,
            "max_retries": 1, "retry_base_delay_seconds": 0, "rate_limit_warning_threshold": 500,
            "rate_limit_wait_enabled": False, "rate_limit_max_wait_seconds": 1,
            "pr_page_size": 100, "commit_page_size": 100, "max_commits_per_pr": 100,
            "impact_min_changed_files": 3, "semantic_keywords": ["refactor", "architecture", "decouple"]}


def pr_node(number: int, title: str = "Refactor component", changed_files: int | None = 3,
            body: str | None = "", author: str | None = "alice") -> dict:
    return {"number": number, "title": title, "body": body, "url": f"https://example.test/pr/{number}",
            "state": "MERGED", "merged": True, "mergedAt": "2026-01-01T00:00:00Z",
            "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
            "changedFiles": changed_files, "author": {"login": author} if author else None,
            "commits": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"commit": {"message": "Refactor internals"}}]}}


def page(nodes: list[dict], has_next: bool = False, cursor: str | None = None) -> dict:
    return {"repository": {"pullRequests": {"nodes": copy.deepcopy(nodes), "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}},
            "rateLimit": {"limit": 5000, "cost": 1, "remaining": 4999, "resetAt": "2026-01-01T01:00:00Z"}}

