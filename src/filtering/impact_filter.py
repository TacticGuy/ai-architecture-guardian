"""Deterministic impact-size criterion."""
from __future__ import annotations
from typing import Any


def passes_impact_filter(pr: dict[str, Any], minimum_changed_files: int = 3) -> bool:
    changed_files = pr.get("changed_files")
    return isinstance(changed_files, int) and not isinstance(changed_files, bool) and changed_files >= minimum_changed_files

