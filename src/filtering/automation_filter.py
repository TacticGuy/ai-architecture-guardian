"""Deterministic rejection of automated dependency-update pull requests."""
from __future__ import annotations

from typing import Any


_KNOWN_AUTOMATION_ACCOUNTS = {
    "dependabot",
    "dependabot[bot]",
    "github-actions",
    "github-actions[bot]",
    "renovate",
    "renovate[bot]",
    "renovate-bot",
}


def is_automated_pr(pr: dict[str, Any]) -> bool:
    """Return true for bot-authored PRs that should not be training candidates."""
    author = pr.get("author")
    if not isinstance(author, str):
        return False
    normalized = author.strip().lower()
    return normalized in _KNOWN_AUTOMATION_ACCOUNTS or normalized.endswith("[bot]")
