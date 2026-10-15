"""Prioritise human diff review without inferring architecture labels."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def blocker_ranked_review_queue(
    audit_rows: Iterable[dict[str, Any]],
    evidence_rows: Iterable[dict[str, Any]],
    reviewed_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return unresolved PRs ordered by the number of sample outcomes they block.

    Priority is workflow metadata only.  Titles and structural counts are copied
    as review context and never converted into decisions or training labels.
    """
    reviewed = reviewed_ids or set()
    blockers: Counter[str] = Counter()
    blocked_samples: dict[str, list[str]] = {}
    for sample in audit_rows:
        sample_id = sample.get("sample_id")
        unresolved = sample.get("unresolved_pr_ids", [])
        if not isinstance(sample_id, str) or not isinstance(unresolved, list):
            continue
        for identifier in set(unresolved):
            if isinstance(identifier, str) and identifier not in reviewed:
                blockers[identifier] += 1
                blocked_samples.setdefault(identifier, []).append(sample_id)

    evidence = {
        row.get("sample_id"): row
        for row in evidence_rows
        if isinstance(row.get("sample_id"), str)
        # The labeller rejects human decisions based on an ambiguous
        # squash/rebase boundary, so do not spend review effort on them.
        and row.get("diff_is_provisional") is not True
    }
    queue = []
    for identifier, count in blockers.items():
        row = evidence.get(identifier)
        if row is None:
            continue
        changes = row.get("production_changes", [])
        syntax = [change.get("syntax", {}) for change in changes if isinstance(change, dict)]
        queue.append({
            "sample_id": identifier,
            "repo": row.get("repo"),
            "pr_number": row.get("pr_number"),
            "merge_commit_sha": row.get("after_sha"),
            "before_commit_sha": row.get("before_sha"),
            "merged_at": row.get("merged_at"),
            "title": row.get("title"),
            "url": row.get("url"),
            "blocked_label_count": count,
            "blocked_sample_ids": sorted(blocked_samples[identifier]),
            "production_python_files": row.get("production_python_files", []),
            "change_statuses": dict(Counter(
                str(change.get("status", "unknown"))[:1] for change in changes
                if isinstance(change, dict)
            )),
            "syntax_evidence_counts": {
                field: sum(len(item.get(field, [])) for item in syntax
                           if isinstance(item.get(field, []), list))
                for field in ("added_imports", "removed_imports",
                              "added_declarations", "removed_declarations")
            },
            "review_status": "pending_human_diff_review",
            "warning": "Priority and syntax evidence are not an architecture decision or risk label.",
        })
    return sorted(queue, key=lambda item: (
        -item["blocked_label_count"], str(item["merged_at"]), item["sample_id"]
    ))
