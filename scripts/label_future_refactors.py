"""Label historical PRs by future architecture-refactor file overlap."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.future_refactor_labels import (
    assign_future_refactor_labels,
)
from src.dataset.label_protocol import pr_id, validate_coverage, validate_event_reviews
from src.dataset.history_matching import HistoryMatcher
from src.storage.jsonl import iter_jsonl, write_jsonl_atomic
from src.utils.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create six-month future-refactor labels before expensive graph building."
    )
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs_v2.jsonl")
    parser.add_argument("--coverage", type=Path, help="Completed collector coverage manifest")
    parser.add_argument("--event-reviews", type=Path, help="Evidence-based PR outcome reviews in JSONL")
    parser.add_argument("--repository-root", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--output", type=Path, default=ROOT / "data/labels/future_refactor_labels_v3.jsonl")
    parser.add_argument("--audit-output", type=Path, default=ROOT / "data/statistics/future_refactor_audit_v3.jsonl")
    parser.add_argument("--repo", help="Limit labelling to one repository, e.g. pytest-dev/pytest")
    parser.add_argument("--horizon-months", type=int, default=6)
    args = parser.parse_args(argv)
    if args.horizon_months <= 0:
        parser.error("--horizon-months must be positive")
    if args.coverage is None or args.event_reviews is None:
        print("Labelling blocked: supply --coverage and --event-reviews. "
              "PR date ranges and refactor keywords alone are insufficient. No outputs changed.")
        return 2
    if not all(path.is_file() for path in (args.raw, args.coverage, args.event_reviews)):
        print("Raw PRs, coverage manifest, or event review file is missing. No outputs changed.")
        return 2

    raw_rows = list(iter_jsonl(args.raw))
    if args.repo:
        raw_rows = [record for record in raw_rows if record.get("repo") == args.repo]
    raw = _unique_records(raw_rows)
    duplicate_count = len(raw_rows) - len(raw)
    if duplicate_count:
        print(f"Deduplicated raw PR rows: {duplicate_count}")
    if not raw:
        print("No matching raw PR records found.")
        return 2

    try:
        manifest = json.loads(args.coverage.read_text(encoding="utf-8"))
        if args.repo and isinstance(manifest, dict):
            manifest = {**manifest, "repositories": [
                entry for entry in manifest.get("repositories", []) if entry.get("repo") == args.repo
            ]}
        windows = validate_coverage(manifest, raw)
        if not windows:
            raise ValueError("Coverage manifest contains no completed repository windows")
        reviews = list(iter_jsonl(args.event_reviews))
        if args.repo:
            sample_ids = {pr_id(record) for record in raw}
            reviews = [review for review in reviews if review.get("sample_id") in sample_ids]
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Labelling blocked: {exc}. No outputs changed.")
        return 2

    settings = load_settings(ROOT / "config/settings.json")
    static_settings = settings["static_analysis"]
    try:
        if len({record.get("repo") for record in raw}) != 1:
            raise ValueError("Run labeling once per repository so its verified Git history stays isolated")
        repo_name = raw[0]["repo"]
        repository = args.repository_root / Path(*repo_name.split("/"))
        matcher = HistoryMatcher(repository, raw, static_settings)
    except Exception as exc:
        print(f"Labelling blocked: could not verify repository history ({type(exc).__name__}: {exc}). No outputs changed.")
        return 2

    changed_files = {identifier: paths for identifier, paths in matcher.files.items()
                      if matcher.records[identifier]["history_status"] == "verified"}
    history_errors = {identifier for identifier, row in matcher.records.items()
                      if row["history_status"] != "verified"}
    # A human decision based on an incomplete first-parent diff cannot resolve
    # an event, and an automatic AST check is generated only for verified PRs.
    reviews = [review for review in reviews if review.get("sample_id") not in history_errors]
    reviewed_ids = {review.get("sample_id") for review in reviews}
    reviews.extend(review for review in matcher.non_executable_reviews()
                   if review["sample_id"] not in reviewed_ids)
    try:
        events, unresolved = validate_event_reviews(reviews, raw, changed_files)
    except ValueError as exc:
        print(f"Labelling blocked: {exc}. No outputs changed.")
        return 2
    unresolved_ids = {pr_id(record) for record in unresolved}
    unresolved.extend({**record, "history_review_unresolved": True}
                      for record in raw if pr_id(record) in history_errors
                      and pr_id(record) not in unresolved_ids)

    # Pairwise matching is limited to each sample's six-month future window.
    # HistoryMatcher checks ancestry and follows production-file identity across
    # the target branch; release-branch overlap is not treated as an outcome.
    from src.dataset.future_refactor_labels import add_calendar_months, parse_timestamp
    history_matches = {}
    for sample in raw:
        sample_time = parse_timestamp(sample.get("merged_at"))
        if sample_time is None:
            continue
        limit = add_calendar_months(sample_time, args.horizon_months)
        sample_id = pr_id(sample)
        pair_results = {}
        for later in raw:
            later_time = parse_timestamp(later.get("merged_at"))
            if later_time is None or not sample_time < later_time <= limit:
                continue
            later_id = pr_id(later)
            pair_results[later_id] = matcher.match(
                sample, later, set(matcher.files.get(sample_id, [])),
                set(matcher.files.get(later_id, [])),
            )
        history_matches[sample_id] = pair_results
    print(f"History verified: {len(raw) - len(history_errors)}/{len(raw)} PRs; "
          f"machine-safe non-architectural reviews: {len([r for r in reviews if r.get('reviewer', '').startswith('automated-')])}")
    print(f"Reviewed architectural events: {len(events)}; unresolved outcomes: {len(unresolved)}")
    labels = assign_future_refactor_labels(
        raw,
        events,
        changed_files,
        windows,
        args.horizon_months,
        history_matches=history_matches,
        unresolved_events=unresolved,
        samples_with_extraction_errors=history_errors,
    )

    labelled = [record for record in labels if record["status"] == "labelled"]
    write_jsonl_atomic(args.output, iter(labelled))
    write_jsonl_atomic(args.audit_output, iter(labels))
    counts = Counter(record["status"] for record in labels)
    positives = sum(record["label"] == 1 for record in labelled)
    negatives = sum(record["label"] == 0 for record in labelled)
    ratio = (100.0 * positives / len(labelled)) if labelled else 0.0
    print(f"Six-month labels: eligible={len(labelled)} positive={positives} negative={negatives} positive_rate={ratio:.1f}%")
    print(f"Excluded: censored={counts['censored']} no_python={counts['excluded_no_python_files']} "
          f"invalid={counts['invalid_metadata']} git_errors={counts['git_error']}")
    print(f"Unknown: coverage={counts['unverified_coverage']} outcomes={counts['unreviewed_outcome']} "
          f"file_extraction={counts['incomplete_file_extraction']}")
    print(f"Training labels: {args.output}")
    print(f"Full audit: {args.audit_output}")
    return 0 if labelled else 1


def _unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = str(record.get("pr_id") or f"{record.get('repo')}#{record.get('pr_number')}")
        result[identifier] = record
    return list(result.values())


if __name__ == "__main__":
    raise SystemExit(main())
