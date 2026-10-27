"""Make the Kaggle upload folder from a built v5 dataset (one command, any OS).

    python scripts/pack_v5_for_kaggle.py --data-dir data/runs/coupling_samples_v5 --out-dir kaggle_v5

Writes into --out-dir:
  graphs_v5.pt.gz          every sample's model input (3-hop graph), compressed
  diffs_v5.jsonl           every sample's diff, for the CodeBERT / CodeReviewer embeddings
  coupling_split_v5.json   the fixed repository split (copied from config/)
  code.zip                 src/, scripts/, config/, requirements.txt
and the teammates' manifest ``v5_manifest.jsonl`` next to them. Upload the first four files
plus notebooks/ai_guardian_v5_kaggle.ipynb as one private Kaggle dataset.
"""
from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_v5_files import main as export_main  # noqa: E402
from src.ml.coupling_data import discover_coupling_samples, pack_graphs  # noqa: E402


def zip_code(target: Path, root: Path = ROOT) -> int:
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in ("src", "scripts", "config"):
            for path in sorted((root / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    archive.write(path, path.relative_to(root).as_posix())
                    count += 1
        if (root / "requirements.txt").is_file():
            archive.write(root / "requirements.txt", "requirements.txt")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "kaggle_v5")
    parser.add_argument("--split", type=Path, default=ROOT / "config/coupling_split_v5.json")
    args = parser.parse_args(argv)
    if not args.split.is_file():
        raise SystemExit(f"{args.split} is missing: the split must be fixed before packing")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    export_main(["--data-dir", str(args.data_dir), "--out-dir", str(args.out_dir), "--split", str(args.split)])
    raw = args.out_dir / "graphs_v5.pt"
    count = pack_graphs(discover_coupling_samples(args.data_dir), raw)
    with raw.open("rb") as source, gzip.open(args.out_dir / "graphs_v5.pt.gz", "wb", compresslevel=6) as target:
        shutil.copyfileobj(source, target)
    raw.unlink()
    shutil.copy(args.split, args.out_dir / "coupling_split_v5.json")
    files = zip_code(args.out_dir / "code.zip")
    sizes = {p.name: round(p.stat().st_size / 1e6, 1) for p in sorted(args.out_dir.iterdir()) if p.is_file()}
    print(f"Packed {count} graphs and {files} code files into {args.out_dir}: {sizes} (MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
