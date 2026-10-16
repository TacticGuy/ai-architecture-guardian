"""Export trained GNN embeddings keyed by PR sample ID for model fusion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.gnn_embeddings import export_gnn_embeddings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export fixed-size GNN embeddings for fusion.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/future_pr_samples_v3")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gnn_embeddings.pt")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--allow-smoke", action="store_true",
                        help="Allow old checkpoints without saved splits; membership will be unknown")
    args = parser.parse_args(argv)
    try:
        summary = export_gnn_embeddings(
            args.data_dir,
            args.checkpoint,
            args.output,
            manifest_path=args.manifest,
            device=args.device,
            batch_size=args.batch_size,
            allow_smoke=args.allow_smoke,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Embedding export failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
