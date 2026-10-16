"""Build BEFORE-only GNN samples from future-refactor labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.builder import DatasetSampleExcluded
from src.dataset.future_builder import build_future_risk_sample
from src.storage.jsonl import iter_jsonl
from src.utils.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build leakage-safe future-risk GNN samples.")
    parser.add_argument("--labels", type=Path, default=ROOT / "data/labels/future_refactor_labels_v3.jsonl")
    parser.add_argument("--repository-root", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/future_pr_samples_v3")
    parser.add_argument("--repo", help="Limit to one repository")
    parser.add_argument("--max-positive", type=int, help="Maximum positive samples to build")
    parser.add_argument("--max-negative", type=int, help="Maximum negative samples to build")
    args = parser.parse_args(argv)
    for value in (args.max_positive, args.max_negative):
        if value is not None and value < 0:
            parser.error("class limits cannot be negative")
    if not args.labels.is_file():
        print(f"Labels not found: {args.labels}")
        return 2

    records = list(iter_jsonl(args.labels))
    invalid = [record.get("sample_id") for record in records
               if record.get("label_protocol_version") != 3]
    if invalid:
        print(f"Build blocked: {len(invalid)} labels are not protocol v3. No graphs built.")
        return 2
    if args.repo:
        records = [record for record in records if record.get("repo") == args.repo]
    records.sort(key=lambda record: (record.get("merged_at") or "", record.get("sample_id") or ""))
    settings = load_settings(ROOT / "config/settings.json")["static_analysis"]
    built = {0: 0, 1: 0}
    selected = {0: 0, 1: 0}
    skipped = excluded = failed = 0
    for record in records:
        label = record.get("label")
        limit = args.max_positive if label == 1 else args.max_negative
        if limit is not None and selected[label] >= limit:
            continue
        repo = record.get("repo")
        number = record.get("pr_number")
        sample_dir = args.output_dir / str(repo).replace("/", "__") / str(number)
        if (sample_dir / "metadata.json").is_file():
            existing = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
            audit_fields = (
                "label", "merge_commit_sha", "label_protocol_version", "horizon_end",
                "observation_start", "observation_end", "triggering_refactor_pr", "event_evidence",
                "history_evidence", "head_ref_sha", "commit_count", "changed_python_files",
            )
            if any(existing.get(field) != record.get(field) for field in audit_fields):
                failed += 1
                print(f"Stale sample: {record.get('sample_id')}; use a new --output-dir after relabelling")
                continue
            graph_path = sample_dir / existing.get("before_graph_path", "")
            if not graph_path.is_file():
                failed += 1
                print(f"Incomplete sample: {record.get('sample_id')}; missing graph, use a new --output-dir")
                continue
            skipped += 1
            selected[label] += 1
            continue
        if sample_dir.exists():
            quarantine = args.output_dir / ".incomplete" / str(repo).replace("/", "__") / f"{number}"
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            if quarantine.exists():
                quarantine = quarantine.with_name(f"{number}-{record.get('merge_commit_sha', '')[:8]}")
            sample_dir.replace(quarantine)
            print(f"Quarantined incomplete sample: {record.get('sample_id')}")
        repository = args.repository_root / Path(*str(repo).split("/"))
        try:
            metadata = build_future_risk_sample(record, repository, args.output_dir, settings)
            built[label] += 1
            selected[label] += 1
            print(f"Built: {metadata['sample_id']} label={label}")
        except DatasetSampleExcluded as exc:
            excluded += 1
            print(f"Excluded: {record.get('sample_id')} ({exc})")
        except Exception as exc:
            failed += 1
            print(f"Failed: {record.get('sample_id')} ({type(exc).__name__}: {exc})")
    summary = {"built_positive": built[1], "built_negative": built[0],
               "selected_positive": selected[1], "selected_negative": selected[0], "skipped": skipped,
               "excluded": excluded, "failed": failed}
    print("Summary: " + json.dumps(summary, sort_keys=True))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
