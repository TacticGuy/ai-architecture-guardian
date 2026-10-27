"""v5.1: add ``history.json`` (pre-merge history features) to every built v5 sample.

    python scripts/build_history_features.py --data-dir data/runs/coupling_samples_v5 \
        --clones data/repositories --workers 12

One worker per repository. Snapshot summaries are cached in the dataset's
``_future_summaries/<repo>/`` folder (the same cache the dataset build uses, so many are
already there). Re-running skips samples that already have ``history.json``.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.coupling_builder import Snapshotter, future_summary  # noqa: E402
from src.dataset.history_features import history_features  # noqa: E402
from src.ml.coupling_data import discover_coupling_samples  # noqa: E402


def build_repository(repo: str, records: list[dict], clones: str, data_dir: str, settings: dict) -> dict[str, int]:
    clone = Path(clones).resolve() / repo.replace("/", "__")
    snapshots = Snapshotter(clone, Path(clones).resolve() / "_worktrees_history" / repo.replace("/", "__"))
    cache = Path(data_dir).resolve() / "_future_summaries" / repo.replace("/", "__")
    counts = {"written": 0, "existing": 0, "failed": 0}
    for record in sorted(records, key=lambda r: r["merged_at"]):
        target = Path(record["_dir"]) / "history.json"
        if target.is_file():
            counts["existing"] += 1
            continue
        try:
            payload = history_features(clone, record, lambda sha: future_summary(snapshots, sha, cache, settings))
        except Exception as exc:  # keep going; the summary line says how many failed
            print(f"{record['sample_id']}: {type(exc).__name__}: {exc}"[:300], flush=True)
            counts["failed"] += 1
            continue
        target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        counts["written"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--clones", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for record in discover_coupling_samples(args.data_dir):
        by_repo[record["repo"]].append(record)
    totals = {"written": 0, "existing": 0, "failed": 0}
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(build_repository, repo, records, str(args.clones), str(args.data_dir), settings): repo
                   for repo, records in sorted(by_repo.items(), key=lambda item: -len(item[1]))}
        for future in as_completed(futures):
            counts = future.result()
            for key, value in counts.items():
                totals[key] += value
            print(f"{futures[future]}: {counts}", flush=True)
    print(f"Done: {totals}")
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
