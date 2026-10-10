"""Print the future architecture-refactor risk for one prepared PR graph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.gnn_inference import predict_graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predict six-month architecture-refactor risk.")
    parser.add_argument("--graph", type=Path, required=True, help="Prepared BEFORE graph.pt")
    parser.add_argument("--checkpoint", type=Path, required=True, help="Trained gnn_future_risk.pt")
    parser.add_argument("--metadata", type=Path, help="Optional sample metadata for the output")
    parser.add_argument("--device", choices=("cpu", "cuda"), help="Default: CUDA when available")
    args = parser.parse_args(argv)
    if not args.graph.is_file():
        parser.error(f"graph does not exist: {args.graph}")
    if not args.checkpoint.is_file():
        parser.error(f"checkpoint does not exist: {args.checkpoint}")

    result = predict_graph(args.graph, args.checkpoint, args.device)
    if args.metadata:
        try:
            metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"could not read metadata: {exc}")
        result["sample_id"] = metadata.get("sample_id")
        result["historical_label"] = metadata.get("label")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
