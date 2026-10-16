"""Create label-blind repository cutoffs and report the resulting cohort."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.gnn_data import discover_samples
from src.ml.split_planning import chronological_cutoffs, split_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/future_pr_samples_v4")
    parser.add_argument("--output", type=Path, default=ROOT / "config/gnn_split_v4.json")
    parser.add_argument("--train-fraction", type=float, default=0.55)
    parser.add_argument("--validation-fraction", type=float, default=0.80)
    args = parser.parse_args(argv)
    try:
        records = discover_samples(args.data_dir)
        cutoffs = chronological_cutoffs(
            records, args.train_fraction, args.validation_fraction,
        )
        report = split_report(records, cutoffs)
    except (OSError, ValueError) as exc:
        print(f"Split planning blocked: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cutoffs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"cutoffs": cutoffs, "report": report}, indent=2, sort_keys=True))
    print(f"Split config: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
