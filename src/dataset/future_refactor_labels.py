"""Create leakage-safe future-refactoring labels from historical pull requests."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from src.filtering.semantic_filter import semantic_filter


LABEL_TYPE = "reviewed_future_architecture_refactor_overlap"
LABEL_PROTOCOL_VERSION = 3


def parse_timestamp(value: object) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp, returning ``None`` for invalid values."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(timezone.utc)
    except ValueError:
        return None


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Advance by calendar months while clamping dates such as 31 August."""
    if months <= 0:
        raise ValueError("months must be positive")
    zero_based_month = value.month - 1 + months
    year = value.year + zero_based_month // 12
    month = zero_based_month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def repository_observation_ends(records: Iterable[dict[str, Any]]) -> dict[str, datetime]:
    """Return the latest observed merged-PR timestamp for every repository."""
    result: dict[str, datetime] = {}
    for record in records:
        repo = record.get("repo")
        merged_at = parse_timestamp(record.get("merged_at"))
        if isinstance(repo, str) and merged_at is not None:
            result[repo] = max(result.get(repo, merged_at), merged_at)
    return result


def explicit_refactor_events(
    records: Iterable[dict[str, Any]], keywords: list[str]
) -> list[dict[str, Any]]:
    """Discover review candidates from titles; this does not validate any label."""
    result: list[dict[str, Any]] = []
    for record in records:
        title_only = {
            "title": record.get("title") or "",
            "body": "",
            "commit_messages": [],
        }
        if semantic_filter(title_only, keywords)[0]:
            result.append(record)
    return result


def is_analysed_python_path(path: str, analysis_settings: Mapping[str, Any]) -> bool:
    """Mirror the Steps 2-5 source-file scope without changing that pipeline."""
    normalised = path.replace("\\", "/")
    parts = [part for part in normalised.split("/") if part]
    if not normalised.endswith(".py") or not parts:
        return False
    excluded_directories = set(analysis_settings.get("excluded_directory_names", []))
    excluded_files = set(analysis_settings.get("excluded_file_names", []))
    if any(part in excluded_directories for part in parts[:-1]) or parts[-1] in excluded_files:
        return False
    if bool(analysis_settings.get("include_tests", False)):
        return True
    return not any(part in {"tests", "test"} or part.startswith("test_") for part in parts)


def assign_future_refactor_labels(
    samples: Iterable[dict[str, Any]],
    refactor_events: Iterable[dict[str, Any]],
    changed_files_by_pr: Mapping[str, Iterable[str]],
    observation_windows: Mapping[str, tuple[datetime, datetime]],
    horizon_months: int = 6,
    *,
    history_matches: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    unresolved_events: Iterable[dict[str, Any]] = (),
    samples_with_extraction_errors: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Assign an observed file-overlap outcome, without claiming PR causation.

    Both classes require the same complete follow-up. Events must carry reviewed
    architectural evidence. Unknown overlapping outcomes block negative labels.
    Coverage windows must come from a validated collection manifest, not min/max
    dates of an arbitrary subset of PR records.
    """
    if horizon_months <= 0:
        raise ValueError("horizon_months must be positive")

    events_by_repo: dict[str, list[tuple[datetime, dict[str, Any], set[str]]]] = defaultdict(list)
    for event in refactor_events:
        if event.get("architecture_review_verified") is not True or not event.get("event_evidence"):
            raise ValueError("Refactor events need verified architectural review evidence")
        repo = event.get("repo")
        event_id = _pr_id(event)
        merged_at = parse_timestamp(event.get("merged_at"))
        files = _normalised_files(event.get("reviewed_affected_files", []))
        if not files or not files <= _normalised_files(changed_files_by_pr.get(event_id, [])):
            raise ValueError(f"Reviewed files do not match changed Python files for {event_id}")
        if isinstance(repo, str) and merged_at is not None and files:
            events_by_repo[repo].append((merged_at, event, files))
    for events in events_by_repo.values():
        events.sort(key=lambda item: item[0])
    unknown_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in unresolved_events:
        unknown_by_repo[event.get("repo")].append(event)
    extraction_error_ids = set(samples_with_extraction_errors)

    labels: list[dict[str, Any]] = []
    for sample in samples:
        repo = sample.get("repo")
        sample_id = _pr_id(sample)
        merged_at = parse_timestamp(sample.get("merged_at"))
        files = _normalised_files(changed_files_by_pr.get(sample_id, []))
        base = {
            "schema_version": 2,
            "label_protocol_version": LABEL_PROTOCOL_VERSION,
            "label_type": LABEL_TYPE,
            "causal_claim": False,
            "sample_id": sample_id,
            "repo": repo,
            "pr_number": sample.get("pr_number"),
            "merge_commit_sha": sample.get("merge_commit_sha"),
            "head_ref_sha": sample.get("head_ref_sha"),
            "commit_count": sample.get("commit_count"),
            "changed_files": sample.get("changed_files"),
            "merged_at": sample.get("merged_at"),
            "horizon_months": horizon_months,
            "changed_python_files": sorted(files),
        }
        if not isinstance(repo, str) or merged_at is None:
            labels.append({**base, "status": "invalid_metadata", "label": None})
            continue
        if not files:
            labels.append({**base, "status": "excluded_no_python_files", "label": None})
            continue

        horizon_end = add_calendar_months(merged_at, horizon_months)
        base["horizon_end"] = horizon_end.isoformat()
        window = observation_windows.get(repo)
        if window is None:
            labels.append({**base, "status": "unverified_coverage", "label": None})
            continue
        if not isinstance(window, tuple) or len(window) != 2:
            raise ValueError("Observation coverage needs a (start, end) interval per repository")
        observed_from, observed_until = window
        base["observation_start"] = observed_from.isoformat()
        base["observation_end"] = observed_until.isoformat()
        if merged_at < observed_from or horizon_end > observed_until:
            labels.append({**base, "status": "censored", "label": None})
            continue
        if sample_id in extraction_error_ids:
            labels.append({**base, "status": "incomplete_sample_history", "label": None})
            continue
        if history_matches is None or sample_id not in history_matches:
            labels.append({**base, "status": "unverified_lineage", "label": None})
            continue
        pair_results = history_matches[sample_id]
        matching_event: tuple[datetime, dict[str, Any], set[str], dict[str, Any]] | None = None
        uncertain_reviewed = []
        for event_time, event, event_files in events_by_repo.get(repo, []):
            if event_time <= merged_at:
                continue
            if event_time > horizon_end:
                break
            result = pair_results.get(_pr_id(event))
            if result is None:
                uncertain_reviewed.append(_pr_id(event))
            elif _verified_history_match(result):
                matched = set(result.get("matched_python_files", [])) & event_files
                if matched:
                    matching_event = (event_time, event, event_files, result)
                    break
            elif not _verified_unrelated_lineage(result):
                uncertain_reviewed.append(_pr_id(event))

        if matching_event is not None:
            event_time, event, event_files, history_evidence = matching_event
            labels.append({
                **base,
                "status": "labelled",
                "label": 1,
                "triggering_refactor_pr": _pr_id(event),
                "triggering_refactor_merged_at": event_time.isoformat(),
                "matched_python_files": sorted(files & event_files),
                "event_evidence": event["event_evidence"],
                "history_evidence": history_evidence.get("history_evidence"),
            })
            continue

        unknown_ids = []
        unknown_history = list(uncertain_reviewed)
        for unknown in unknown_by_repo.get(repo, []):
            event_time = parse_timestamp(unknown.get("merged_at"))
            if event_time is not None and merged_at < event_time <= horizon_end:
                unknown_id = _pr_id(unknown)
                result = pair_results.get(unknown_id)
                if result is None:
                    unknown_history.append(unknown_id)
                elif _verified_history_match(result) and (
                    set(result.get("matched_python_files", []))
                    & _normalised_files(changed_files_by_pr.get(unknown_id, []))
                ):
                    unknown_ids.append(_pr_id(unknown))
                elif not (_verified_history_match(result) or _verified_unrelated_lineage(result)):
                    unknown_history.append(unknown_id)
        if unknown_ids:
            labels.append({**base, "status": "unreviewed_outcome", "label": None,
                           "unresolved_pr_ids": sorted(unknown_ids)})
            continue
        if unknown_history:
            labels.append({**base, "status": "unverified_followup_history", "label": None,
                           "unresolved_pr_ids": sorted(set(unknown_history))})
            continue
        labels.append({
            **base,
            "status": "labelled",
            "label": 0,
            "triggering_refactor_pr": None,
            "matched_python_files": [],
        })
    return labels


def _pr_id(record: Mapping[str, Any]) -> str:
    identifier = record.get("pr_id")
    if isinstance(identifier, str) and identifier:
        return identifier
    return f"{record.get('repo')}#{record.get('pr_number')}"


def _normalised_files(paths: Iterable[str]) -> set[str]:
    return {path.strip().replace("\\", "/") for path in paths if isinstance(path, str) and path.strip()}


def _verified_history_match(result: Mapping[str, Any] | None) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "verified":
        return False
    evidence = result.get("history_evidence")
    return (isinstance(evidence, Mapping)
            and evidence.get("history_validation_version") == 1
            and evidence.get("ancestry_verified") is True
            and evidence.get("same_target_history") is True
            and evidence.get("file_identity") == "unchanged_paths")


def _verified_unrelated_lineage(result: Mapping[str, Any] | None) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "unrelated_lineage":
        return False
    evidence = result.get("history_evidence")
    return (isinstance(evidence, Mapping)
            and evidence.get("history_validation_version") == 1
            and evidence.get("ancestry_verified") is True
            and evidence.get("same_target_history") is False)
