"""Streaming impact-then-semantic filter pipeline."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterator

from src.filtering.automation_filter import is_automated_pr
from src.filtering.impact_filter import passes_impact_filter
from src.filtering.semantic_filter import semantic_filter


@dataclass
class FilterStatistics:
    total_raw_prs: int = 0
    automation_rejected: int = 0
    impact_passed: int = 0
    impact_rejected: int = 0
    semantic_passed: int = 0
    semantic_rejected: int = 0
    final_accepted: int = 0
    keyword_frequencies: Counter[str] = field(default_factory=Counter)


def evaluate_record(pr: dict[str, Any], minimum_changed_files: int, keywords: list[str],
                    statistics: FilterStatistics) -> dict[str, Any]:
    """Return an auditable decision record while updating exactly one statistics object."""
    statistics.total_raw_prs += 1
    result = dict(pr)
    result["automation_filter"] = not is_automated_pr(result)
    if not result["automation_filter"]:
        statistics.automation_rejected += 1
        result["impact_filter"] = False
        result["semantic_filter"] = False
        result["matched_keywords"] = []
        result["filter_status"] = "rejected_automation"
        return result
    result["impact_filter"] = passes_impact_filter(result, minimum_changed_files)
    result["matched_keywords"] = []
    if not result["impact_filter"]:
        statistics.impact_rejected += 1
        result["semantic_filter"] = False
        result["filter_status"] = "rejected_impact"
        return result
    statistics.impact_passed += 1
    semantic_pass, matched = semantic_filter(result, keywords)
    result["semantic_filter"] = semantic_pass
    result["matched_keywords"] = matched
    if not semantic_pass:
        statistics.semantic_rejected += 1
        result["filter_status"] = "rejected_semantic"
        return result
    statistics.semantic_passed += 1
    statistics.final_accepted += 1
    statistics.keyword_frequencies.update(matched)
    result["filter_status"] = "accepted"
    return result


def filter_records(records: Iterator[dict[str, Any]], minimum_changed_files: int,
                   keywords: list[str], statistics: FilterStatistics | None = None) -> Iterator[dict[str, Any]]:
    stats = statistics if statistics is not None else FilterStatistics()
    for pr in records:
        result = evaluate_record(pr, minimum_changed_files, keywords, stats)
        if result["filter_status"] == "accepted":
            yield result


def write_filter_outputs(records: Iterator[dict[str, Any]], filtered_path: str | Path, audit_path: str | Path,
                         minimum_changed_files: int, keywords: list[str], statistics: FilterStatistics) -> int:
    """Stream accepted records and every decision to separate atomically-replaced JSONL files."""
    filtered, audit = Path(filtered_path), Path(audit_path)
    filtered.parent.mkdir(parents=True, exist_ok=True)
    audit.parent.mkdir(parents=True, exist_ok=True)
    filtered_tmp, audit_tmp = filtered.with_suffix(filtered.suffix + ".tmp"), audit.with_suffix(audit.suffix + ".tmp")
    accepted = 0
    with filtered_tmp.open("w", encoding="utf-8", newline="\n") as filtered_handle, audit_tmp.open("w", encoding="utf-8", newline="\n") as audit_handle:
        for pr in records:
            result = evaluate_record(pr, minimum_changed_files, keywords, statistics)
            encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            audit_handle.write(encoded)
            if result["filter_status"] == "accepted":
                filtered_handle.write(encoded)
                accepted += 1
    filtered_tmp.replace(filtered)
    audit_tmp.replace(audit)
    return accepted
