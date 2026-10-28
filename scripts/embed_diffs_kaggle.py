"""Embed every v5 diff with CodeBERT and CodeReviewer on a GPU (Kaggle) or any machine.

    python scripts/embed_diffs_kaggle.py --diffs diffs_v5.jsonl --output-dir embeddings_v5

``diffs_v5.jsonl`` has one {"sample_id", "diff"} object per line (made by
scripts/export_diffs.py). Uses the project's own DiffEncoder, so the vectors are made exactly
like the earlier versions: production files only, <add>/<del>/<keep> markers when the model
knows them, overlapping 512-token windows averaged into one vector per PR.
Writes ``<model>.pt`` = {sample_id: 768-number tensor} plus ``<model>.json`` with the settings.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from src.semantic.diff_encoder import DiffEncoder, EncoderSettings  # noqa: E402

MODELS = {"codebert": "microsoft/codebert-base", "codereviewer": "microsoft/codereviewer"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--diffs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    parser.add_argument("--max-chunks", type=int, default=16)
    args = parser.parse_args(argv)
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    rows = [json.loads(line) for line in args.diffs.read_text(encoding="utf-8").splitlines() if line.strip()]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for short in args.models:
        encoder = DiffEncoder.from_pretrained(MODELS[short], EncoderSettings(max_chunks=args.max_chunks, batch_size=16),
                                              device=device)
        vectors, started = {}, time.perf_counter()
        for index, row in enumerate(rows, 1):
            vectors[row["sample_id"]] = encoder.encode_diff(row["diff"], settings).vector
            if index % 250 == 0:
                print(f"{short}: {index}/{len(rows)} in {time.perf_counter() - started:.0f}s", flush=True)
        torch.save(vectors, args.output_dir / f"{short}.pt")
        (args.output_dir / f"{short}.json").write_text(json.dumps({**encoder.describe(), "device": device,
                                                                   "count": len(vectors)}, indent=2), encoding="utf-8")
        print(f"{short}: saved {len(vectors)} vectors on {device}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
