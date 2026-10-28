"""Export the v5 dataset's hand-off files: the sample manifest and the diffs for Kaggle.

    python scripts/export_v5_files.py --data-dir data/coupling_samples_v5 --out-dir data

Writes
  * ``v5_manifest.jsonl``  one line per sample (the teammates' data contract): sample_id, repo,
    number, title, merged_at, before/merge commit, changed files, touched modules, split, label
  * ``diffs_v5.jsonl``     {"sample_id", "diff"} per sample, the input of embed_diffs_kaggle.py
The split is read from ``config/coupling_split_v5.json`` (written by train_coupling_gnn.py);
if it does not exist yet it is computed with the same function and saved, so every script
uses one split.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.coupling_data import discover_coupling_samples, repository_split  # noqa: E402

SPLIT_NAMES = {"train": "train", "validation": "val", "test": "test"}


def load_or_create_split(records: list[dict], path: Path) -> dict[str, list[str]]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    split = repository_split(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    return split


def manifest_row(record: dict, split_of: dict[str, str]) -> dict:
    return {"sample_id": record["sample_id"], "repo": record["repo"], "number": record["pr_number"],
            "title": record.get("title", ""), "merged_at": record["merged_at"],
            "before_commit_sha": record["before_commit_sha"], "merge_commit_sha": record["merge_commit_sha"],
            "changed_python_files": record["changed_python_files"], "touched_modules": record["touched_modules"],
            "split": SPLIT_NAMES[split_of[record["repo"]]], "label": record["label"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/coupling_samples_v5")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--split", type=Path, default=ROOT / "config/coupling_split_v5.json")
    args = parser.parse_args(argv)
    records = discover_coupling_samples(args.data_dir)
    split = load_or_create_split(records, args.split)
    split_of = {repo: name for name, repos in split.items() for repo in repos}
    missing = sorted({r["repo"] for r in records} - set(split_of))
    if missing:
        raise SystemExit(f"Repositories missing from {args.split}: {missing}. Delete the split file only "
                         "if no model has been trained on it yet.")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "v5_manifest.jsonl").open("w", encoding="utf-8") as manifest, \
            (args.out_dir / "diffs_v5.jsonl").open("w", encoding="utf-8") as diffs:
        for record in records:
            manifest.write(json.dumps(manifest_row(record, split_of)) + "\n")
            diff = (Path(record["_dir"]) / record.get("diff_path", "diff.patch")).read_text(encoding="utf-8",
                                                                                          errors="replace")
            diffs.write(json.dumps({"sample_id": record["sample_id"], "diff": diff}) + "\n")
    counts = {name: sum(1 for r in records if split_of[r["repo"]] == name) for name in split}
    print(f"Exported {len(records)} samples; per split {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
