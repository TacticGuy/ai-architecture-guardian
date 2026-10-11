"""Audit a collected historical window against a local clone without labelling."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.history_audit import audit_repository
from src.dataset.git_snapshots import GitSnapshotError
from src.dataset.label_protocol import validate_coverage
from src.storage.jsonl import iter_jsonl, write_jsonl_atomic
from src.utils.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs_v2.jsonl")
    parser.add_argument("--coverage", type=Path, default=ROOT / "data/raw/coverage_v2.json")
    parser.add_argument("--repository-root", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/statistics")
    args = parser.parse_args(argv)
    components = args.repo.split("/")
    if len(components) != 2 or any(not value or value in {".", ".."} or "\\" in value for value in components):
        parser.error("--repo must be owner/name")
    if not args.raw.is_file() or not args.coverage.is_file():
        parser.error("Raw collection and coverage manifest must exist")
    records = [row for row in iter_jsonl(args.raw) if row.get("repo") == args.repo]
    if not records:
        parser.error("No records for this repository")
    manifest = json.loads(args.coverage.read_text(encoding="utf-8"))
    manifest["repositories"] = [entry for entry in manifest.get("repositories", []) if entry.get("repo") == args.repo]
    windows = validate_coverage(manifest, records)
    if args.repo not in windows:
        parser.error("No verified coverage for repository")
    settings = load_settings(ROOT / "config/settings.json")["static_analysis"]
    try:
        rows, summary = audit_repository(
            args.repository_root.joinpath(*components), records, settings, windows[args.repo][1].isoformat(),
            progress=lambda done, total: print(f"Audited {done}/{total}", flush=True),
        )
    except (GitSnapshotError, ValueError) as exc:
        print(f"Audit blocked: {exc}. Existing audit outputs unchanged.")
        return 2
    slug = "__".join(components)
    output = args.output_dir / f"{slug}_history_audit.jsonl"
    summary_path = args.output_dir / f"{slug}_history_audit_summary.json"
    write_jsonl_atomic(output, iter(rows))
    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(summary_path)
    print(json.dumps({key: value for key, value in summary.items() if key not in {"diff_review_candidates", "overlap_audit"}}, indent=2))
    print(f"Evidence rows: {output}\nSummary: {summary_path}")
    return 0 if not summary["statuses"].get("git_or_evidence_error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
