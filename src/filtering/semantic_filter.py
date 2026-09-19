"""Case-insensitive deterministic substring keyword matching."""
from __future__ import annotations
from typing import Any


def semantic_filter(pr: dict[str, Any], keywords: list[str]) -> tuple[bool, list[str]]:
    fields: list[str] = [pr.get("title") or "", pr.get("body") or ""]
    fields.extend(message for message in (pr.get("commit_messages") or []) if isinstance(message, str))
    searchable = "\n".join(field for field in fields if isinstance(field, str)).lower()
    matched = [keyword for keyword in keywords if keyword.lower() in searchable]
    return bool(matched), matched

