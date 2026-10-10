"""Create leakage-safe future-refactoring labels from historical pull requests."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.filtering.semantic_filter import semantic_filter


LABEL_TYPE = "future_refactor_file_overlap"


def parse_timestamp(value: object) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp, returning ``None`` for invalid values."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
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
    """Keep high-precision events whose PR title explicitly states refactor intent.

    Commit messages and long bodies may mention incidental internal refactoring in
    an otherwise unrelated fix or formatter PR. They are useful during candidate
    discovery but are deliberately insufficient for the final future-risk label.
    """
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
    observation_ends: Mapping[str, datetime],
    horizon_months: int = 6,
) -> list[dict[str, Any]]:
    """Label PRs using later refactor PRs that overlap their changed Python files.

    A positive is known as soon as a matching future event is observed. A negative
    requires the entire horizon to be observable. Records without that follow-up
    are marked ``censored`` rather than incorrectly treated as safe.
    """
    if horizon_months <= 0:
        raise ValueError("horizon_months must be positive")

    events_by_repo: dict[str, list[tuple[datetime, dict[str, Any], set[str]]]] = defaultdict(list)
    for event in refactor_events:
        repo = event.get("repo")
        event_id = _pr_id(event)
        merged_at = parse_timestamp(event.get("merged_at"))
        files = _normalised_files(changed_files_by_pr.get(event_id, []))
        if isinstance(repo, str) and merged_at is not None and files:
            events_by_repo[repo].append((merged_at, event, files))
    for events in events_by_repo.values():
        events.sort(key=lambda item: item[0])

    labels: list[dict[str, Any]] = []
    for sample in samples:
        repo = sample.get("repo")
        sample_id = _pr_id(sample)
        merged_at = parse_timestamp(sample.get("merged_at"))
        files = _normalised_files(changed_files_by_pr.get(sample_id, []))
        base = {
            "schema_version": 1,
            "label_type": LABEL_TYPE,
            "sample_id": sample_id,
            "repo": repo,
            "pr_number": sample.get("pr_number"),
            "merge_commit_sha": sample.get("merge_commit_sha"),
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
        matching_event: tuple[datetime, dict[str, Any], set[str]] | None = None
        for event_time, event, event_files in events_by_repo.get(repo, []):
            if event_time <= merged_at:
                continue
            if event_time > horizon_end:
                break
            if files & event_files:
                matching_event = (event_time, event, event_files)
                break

        if matching_event is not None:
            event_time, event, event_files = matching_event
            labels.append({
                **base,
                "status": "labelled",
                "label": 1,
                "triggering_refactor_pr": _pr_id(event),
                "triggering_refactor_merged_at": event_time.isoformat(),
                "matched_python_files": sorted(files & event_files),
            })
            continue

        observed_until = observation_ends.get(repo)
        if observed_until is None or observed_until < horizon_end:
            labels.append({
                **base,
                "status": "censored",
                "label": None,
                "observed_until": observed_until.isoformat() if observed_until else None,
            })
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
