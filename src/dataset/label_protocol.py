"""Validate collection coverage and evidence used by the outcome labeller."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from src.dataset.future_refactor_labels import parse_timestamp


def pr_id(record: Mapping[str, Any]) -> str:
    return str(record.get("pr_id") or f"{record.get('repo')}#{record.get('pr_number')}")


def validate_coverage(
    manifest: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, tuple[datetime, datetime]]:
    """Validate a collector manifest against the exact raw PR IDs for each window.

    This verifies consistency, not completeness from dates alone. The collector
    must only mark pagination_completed after exhausting its date-window query.
    """
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("repositories"), list):
        raise ValueError("Coverage manifest needs schema_version=1 and repositories")
    result = {}
    for entry in manifest["repositories"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid coverage repository entry")
        repo = entry.get("repo")
        start = parse_timestamp(entry.get("window_start"))
        end = parse_timestamp(entry.get("window_end"))
        collected = entry.get("collected_pr_ids")
        if not isinstance(repo, str) or repo in result or start is None or end is None or start >= end:
            raise ValueError("Coverage has invalid repository, timezone, duplicate, or interval")
        if entry.get("pagination_completed") is not True:
            raise ValueError(f"Collection pagination is incomplete for {repo}")
        if (entry.get("source") != "github_repository_pull_requests"
                or entry.get("order") != "CREATED_AT_ASC"):
            raise ValueError(f"Coverage does not identify the historical collection method for {repo}")
        reason = entry.get("completion_reason")
        if reason not in {"connection_exhausted", "created_after_window_end"}:
            raise ValueError(f"Coverage has no traversal completion reason for {repo}")
        if reason == "created_after_window_end":
            last_created = parse_timestamp(entry.get("last_created_at"))
            if last_created is None or last_created <= end:
                raise ValueError(f"Coverage has no creation-date boundary proof for {repo}")
        if not isinstance(collected, list) or not all(isinstance(x, str) for x in collected):
            raise ValueError(f"Coverage PR IDs are missing for {repo}")
        if len(set(collected)) != len(collected):
            raise ValueError(f"Coverage contains duplicate PR IDs for {repo}")
        actual = set()
        for record in records:
            if record.get("repo") != repo:
                continue
            timestamp = parse_timestamp(record.get("merged_at"))
            if timestamp is None:
                raise ValueError(f"Raw record has invalid merge timestamp: {pr_id(record)}")
            if start <= timestamp <= end:
                actual.add(pr_id(record))
        if actual != set(collected):
            raise ValueError(f"Coverage PR IDs do not match the raw collection for {repo}")
        result[repo] = (start, end)
    return result


def validate_event_reviews(
    reviews: Iterable[dict[str, Any]],
    records: list[dict[str, Any]],
    changed_files: Mapping[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return evidence-backed architecture events and unresolved Python changes.

    Missing/uncertain reviews remain unresolved. Titles, messages, automation
    flags and repository identity never determine an architectural outcome here.
    """
    by_id = {pr_id(record): record for record in records}
    resolved: set[str] = set()
    seen: set[str] = set()
    accepted = []
    for review in reviews:
        identifier = review.get("sample_id")
        if not isinstance(identifier, str) or identifier not in by_id or identifier in seen:
            raise ValueError(f"Review references an unknown or duplicate PR: {identifier!r}")
        seen.add(identifier)
        source = by_id[identifier]
        if not source.get("merge_commit_sha") or review.get("merge_commit_sha") != source["merge_commit_sha"]:
            raise ValueError(f"Review commit does not match the collected PR: {identifier}")
        decision = review.get("decision")
        if decision not in {"architecture_refactor", "non_architectural", "uncertain"}:
            raise ValueError(f"Invalid event review decision for {identifier}")
        candidate_eligible = review.get("candidate_training_eligible", True)
        if not isinstance(candidate_eligible, bool):
            raise ValueError(f"Review {identifier} has invalid candidate_training_eligible")
        if candidate_eligible is False and (
            not isinstance(review.get("candidate_exclusion_reason"), str)
            or not review["candidate_exclusion_reason"].strip()
        ):
            raise ValueError(f"Review {identifier} needs candidate_exclusion_reason")
        if decision == "uncertain":
            continue
        for field in ("reviewer", "rationale"):
            if not isinstance(review.get(field), str) or not review[field].strip():
                raise ValueError(f"Review {identifier} needs {field}")
        references = review.get("evidence_refs")
        if not isinstance(references, list) or not references or not all(
            isinstance(ref, str) and ref.strip() for ref in references
        ):
            raise ValueError(f"Review {identifier} needs evidence references")
        if decision == "architecture_refactor":
            affected = review.get("affected_python_files")
            if not isinstance(affected, list) or not affected or not all(isinstance(x, str) for x in affected):
                raise ValueError(f"Review {identifier} needs affected production Python files")
            normalised = {path.strip().replace("\\", "/") for path in affected}
            if not normalised <= set(changed_files.get(identifier, [])):
                raise ValueError(f"Reviewed affected files do not match Git changes for {identifier}")
            accepted.append({
                **source,
                "architecture_review_verified": True,
                "reviewed_affected_files": sorted(normalised),
                "event_evidence": {
                    "reviewer": review["reviewer"],
                    "rationale": review["rationale"],
                    "references": references,
                },
            })
        resolved.add(identifier)
    unresolved = [
        record for record in records
        if changed_files.get(pr_id(record)) and pr_id(record) not in resolved
    ]
    return accepted, unresolved
