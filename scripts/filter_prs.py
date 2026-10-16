"""Produce the accepted deterministic filtered dataset from raw JSONL."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.filtering.pipeline import FilterStatistics, write_filter_outputs
from src.storage.jsonl import iter_jsonl
from src.utils.config import load_settings
from src.utils.logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply impact and keyword filters to raw PR JSONL.")
    parser.add_argument("--input", default=ROOT / "data/raw/raw_prs.jsonl", type=Path)
    parser.add_argument("--output", default=ROOT / "data/filtered/filtered_prs.jsonl", type=Path)
    parser.add_argument("--audit-output", default=ROOT / "data/statistics/filtering_decisions.jsonl", type=Path,
                        help="Per-PR accept/reject decision audit JSONL")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logger = configure_logging(ROOT / "logs/pipeline.log", args.verbose)
    if not args.input.exists():
        print(f"Raw dataset does not exist: {args.input}")
        return 1
    settings = load_settings(ROOT / "config/settings.json")
    stats = FilterStatistics()
    count = write_filter_outputs(iter_jsonl(args.input), args.output, args.audit_output,
                                 int(settings["impact_min_changed_files"]), list(settings["semantic_keywords"]), stats)
    logger.info("Filtering completed: %d accepted from %d raw PRs", count, stats.total_raw_prs)
    print(f"Filtering complete: {count} accepted from {stats.total_raw_prs} raw PRs")
    print(f"Automation rejected: {stats.automation_rejected}")
    print(f"Impact passed/rejected: {stats.impact_passed}/{stats.impact_rejected}")
    print(f"Semantic passed/rejected: {stats.semantic_passed}/{stats.semantic_rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
