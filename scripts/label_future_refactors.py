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
    explicit_refactor_events,
    is_analysed_python_path,
    repository_observation_ends,
)
from src.dataset.git_snapshots import changed_python_files, resolve_commit_pair
from src.storage.jsonl import iter_jsonl, write_jsonl_atomic
from src.utils.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create six-month future-refactor labels before expensive graph building."
    )
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs.jsonl")
    parser.add_argument("--events", type=Path, default=ROOT / "data/filtered/filtered_prs.jsonl")
    parser.add_argument("--repository-root", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--output", type=Path, default=ROOT / "data/labels/future_refactor_labels.jsonl")
    parser.add_argument("--audit-output", type=Path, default=ROOT / "data/statistics/future_refactor_audit.jsonl")
    parser.add_argument("--repo", help="Limit labelling to one repository, e.g. pytest-dev/pytest")
    parser.add_argument("--horizon-months", type=int, default=6)
    args = parser.parse_args(argv)
    if args.horizon_months <= 0:
        parser.error("--horizon-months must be positive")
    if not args.raw.is_file() or not args.events.is_file():
        print("Raw PRs or filtered refactor events are missing. Run scrape_prs.py and filter_prs.py first.")
        return 2

    raw_rows = list(iter_jsonl(args.raw))
    candidate_rows = list(iter_jsonl(args.events))
    if args.repo:
        raw_rows = [record for record in raw_rows if record.get("repo") == args.repo]
        candidate_rows = [record for record in candidate_rows if record.get("repo") == args.repo]
    raw = _unique_records(raw_rows)
    candidate_events = _unique_records(candidate_rows)
    duplicate_count = len(raw_rows) - len(raw)
    if duplicate_count:
        print(f"Deduplicated raw PR rows: {duplicate_count}")
    if not raw:
        print("No matching raw PR records found.")
        return 2

    settings = load_settings(ROOT / "config/settings.json")
    static_settings = settings["static_analysis"]
    events = explicit_refactor_events(candidate_events, list(settings["semantic_keywords"]))
    print(f"Explicit refactor events: {len(events)} from {len(candidate_events)} filtered candidates")
    changed_files: dict[str, list[str]] = {}
    extraction_errors: dict[str, str] = {}
    for record in _unique_records(raw + events):
        identifier = str(record.get("pr_id") or f"{record.get('repo')}#{record.get('pr_number')}")
        repo = record.get("repo")
        sha = record.get("merge_commit_sha")
        if not isinstance(repo, str) or not isinstance(sha, str):
            extraction_errors[identifier] = "missing repository or merge commit SHA"
            continue
        repository = args.repository_root / Path(*repo.split("/"))
        try:
            pair = resolve_commit_pair(repository, sha)
            files = changed_python_files(repository, pair)
            changed_files[identifier] = [
                path for path in files if is_analysed_python_path(path, static_settings)
            ]
        except Exception as exc:
            extraction_errors[identifier] = f"{type(exc).__name__}: {exc}"

    labels = assign_future_refactor_labels(
        raw,
        events,
        changed_files,
        repository_observation_ends(raw),
        args.horizon_months,
    )
    for record in labels:
        error = extraction_errors.get(record["sample_id"])
        if error:
            record["status"] = "git_error"
            record["label"] = None
            record["error"] = error

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
