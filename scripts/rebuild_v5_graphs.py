"""Re-extract every v5 sample's graphs with the current code (labels are checked, not changed).

    python scripts/rebuild_v5_graphs.py --data-dir data/runs/coupling_samples_v5 \
        --clones data/repositories --workers 12

Used after a graph-extraction fix (v5.1: type annotations are no longer counted as global-variable
accesses, validation bug B2). For each sample the label is recomputed from the new graph and
must match the stored label; any sample whose label would change is listed in
``rebuild_log.jsonl`` and left untouched. Re-running skips samples already rebuilt with the same
``--extractor`` tag. ``history.json`` and ``diff.patch`` are not touched (they do not depend on
the symbol-level graph).
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

from src.dataset.coupling_builder import Snapshotter, rebuild_sample_graph  # noqa: E402
from src.ml.coupling_data import discover_coupling_samples  # noqa: E402

EXTRACTOR = "v5.1-annotations-not-globals"


def rebuild_repository(repo: str, records: list[dict], clones: str, data_dir: str, settings: dict,
                       extractor: str) -> list[dict]:
    clone = Path(clones).resolve() / repo.replace("/", "__")
    snapshots = Snapshotter(clone, Path(clones).resolve() / "_worktrees_rebuild" / repo.replace("/", "__"))
    cache = Path(data_dir).resolve() / "_future_summaries" / repo.replace("/", "__")
    results = []
    for record in sorted(records, key=lambda r: r["merged_at"]):
        if record.get("extractor") == extractor:
            results.append({"sample_id": record["sample_id"], "status": "existing"})
            continue
        try:
            results.append(rebuild_sample_graph(record, snapshots, cache, settings, extractor))
        except Exception as exc:  # keep going; reported at the end
            results.append({"sample_id": record["sample_id"], "status": "failed",
                            "reason": f"{type(exc).__name__}: {exc}"[:300]})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--clones", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--extractor", default=EXTRACTOR)
    args = parser.parse_args(argv)
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for record in discover_coupling_samples(args.data_dir):
        by_repo[record["repo"]].append(record)
    totals: dict[str, int] = defaultdict(int)
    log_path = args.data_dir / "rebuild_log.jsonl"
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool, log_path.open("a", encoding="utf-8") as log:
        futures = {pool.submit(rebuild_repository, repo, records, str(args.clones), str(args.data_dir), settings,
                               args.extractor): repo
                   for repo, records in sorted(by_repo.items(), key=lambda item: -len(item[1]))}
        for future in as_completed(futures):
            results = future.result()
            counts: dict[str, int] = defaultdict(int)
            for result in results:
                counts[result["status"]] += 1
                totals[result["status"]] += 1
                if result["status"] != "existing":
                    log.write(json.dumps(result) + "\n")
            log.flush()
            print(f"{futures[future]}: {dict(counts)}", flush=True)
    print(f"Done: {dict(totals)}")
    if totals["label_changed"] or totals["failed"]:
        print(f"See {log_path} for samples whose label would change or that failed (they were NOT modified).")
    return 0 if not totals["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
