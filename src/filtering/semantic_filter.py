"""Deterministic keyword matching over human-authored PR text."""
from __future__ import annotations
import re
from typing import Any


def semantic_filter(pr: dict[str, Any], keywords: list[str]) -> tuple[bool, list[str]]:
    fields: list[str] = [pr.get("title") or "", _without_details(pr.get("body") or "")]
    fields.extend(
        message.splitlines()[0]
        for message in (pr.get("commit_messages") or [])
        if isinstance(message, str) and message.splitlines()
    )
    searchable = "\n".join(field for field in fields if isinstance(field, str)).lower()
    matched = [keyword for keyword in keywords if _contains_phrase(searchable, keyword)]
    return bool(matched), matched


def _without_details(text: str) -> str:
    """Remove generated release-note/changelog blocks commonly embedded by bots."""
    return re.sub(r"<details\b[^>]*>.*?</details\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)


def _contains_phrase(searchable: str, keyword: str) -> bool:
    phrase = keyword.strip().lower()
    if not phrase:
        return False
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", searchable) is not None

