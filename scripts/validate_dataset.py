"""Validate JSONL integrity and filtering provenance."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.filtering.impact_filter import passes_impact_filter
from src.filtering.semantic_filter import semantic_filter
from src.storage.jsonl import JSONLFormatError, iter_jsonl
from src.utils.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate raw and accepted PR datasets.")
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs.jsonl")
    parser.add_argument("--filtered", type=Path, default=ROOT / "data/filtered/filtered_prs.jsonl")
    args = parser.parse_args()
    failures: list[str] = []
    if not args.raw.exists(): failures.append(f"Raw JSONL does not exist: {args.raw}")
    if not args.filtered.exists(): failures.append(f"Filtered JSONL does not exist: {args.filtered}")
    if failures:
        print("DATASET VALIDATION FAILED\n" + "\n".join(failures)); return 1
    settings = load_settings(ROOT / "config/settings.json")
    raw_ids: set[str] = set()
    try:
        for line, pr in enumerate(iter_jsonl(args.raw), 1):
            for field in ("repo", "pr_number", "title", "pr_id"):
                if field not in pr or pr[field] in (None, ""):
                    failures.append(f"raw line {line}: missing {field}")
            pr_id = pr.get("pr_id")
            if pr_id in raw_ids: failures.append(f"raw line {line}: duplicate pr_id {pr_id}")
            if pr_id: raw_ids.add(str(pr_id))
    except JSONLFormatError as exc:
        failures.append(str(exc))
    filtered_ids: set[str] = set()
    try:
        for line, pr in enumerate(iter_jsonl(args.filtered), 1):
            pr_id = pr.get("pr_id")
            if not pr_id: failures.append(f"filtered line {line}: missing pr_id")
            if pr_id in filtered_ids: failures.append(f"filtered line {line}: duplicate pr_id {pr_id}")
            if pr_id: filtered_ids.add(str(pr_id))
            if pr_id not in raw_ids: failures.append(f"filtered line {line}: {pr_id} does not originate from raw dataset")
            if not passes_impact_filter(pr, int(settings["impact_min_changed_files"])): failures.append(f"filtered line {line}: fails impact criterion")
            passed, matches = semantic_filter(pr, list(settings["semantic_keywords"]))
            if not passed or not pr.get("matched_keywords"): failures.append(f"filtered line {line}: lacks semantic keyword")
            if pr.get("matched_keywords") != matches: failures.append(f"filtered line {line}: recorded keywords are not deterministic matches")
            if pr.get("filter_status") != "accepted": failures.append(f"filtered line {line}: status is not accepted")
            if pr.get("impact_filter") is not True or pr.get("semantic_filter") is not True: failures.append(f"filtered line {line}: recorded filters are not true")
    except JSONLFormatError as exc:
        failures.append(str(exc))
    if failures:
        print("DATASET VALIDATION FAILED\n" + "\n".join(failures)); return 1
    print("DATASET VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

