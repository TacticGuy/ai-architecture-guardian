"""Build the v5 future-coupling dataset from local clones (no GitHub API needed).

    python scripts/build_coupling_dataset.py --repos config/coupling_repositories.json \
        --clones data/repositories --output data/coupling_samples_v5 --per-repo 120 --workers 2

Each repository is processed by one worker: its merged PRs are read from the first-parent
history, PRs whose outcome window is not fully observed are dropped, up to ``--per-repo``
PRs are taken evenly over time, and each becomes a sample (see src/dataset/coupling_builder.py).
Re-running skips samples that already exist, so an interrupted build continues where it stopped.
A log line per PR (built or skipped, with the reason and seconds) goes to ``<output>/build_log.jsonl``.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.coupling_builder import SampleSkipped, Snapshotter, build_coupling_sample, future_moment  # noqa: E402
from src.dataset.pr_history import last_commit_time, merged_prs_from_history  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", type=Path, default=ROOT / "config/coupling_repositories.json")
    parser.add_argument("--clones", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--output", type=Path, default=ROOT / "data/coupling_samples_v5")
    parser.add_argument("--per-repo", type=int, default=120)
    parser.add_argument("--since", default="2018-01-01T00:00:00+00:00", help="ignore PRs merged before this")
    parser.add_argument("--horizon-months", type=int, default=6)
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="excess coupling growth (links per touched module) that counts as degrading")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--only", nargs="*", help="limit to these owner/name repositories")
    args = parser.parse_args(argv)

    repos = [f"{item['owner']}/{item['name']}" for item in json.loads(args.repos.read_text(encoding="utf-8"))
             if item.get("enabled", True)]
    if args.only:
        repos = [repo for repo in repos if repo in set(args.only)]
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = [(repo, str(args.clones), str(args.output), args.per_repo, args.since, args.horizon_months,
             args.threshold, settings) for repo in repos]
    totals = {"built": 0, "skipped": 0, "existing": 0, "failed": 0}
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(build_repository, *job): job[0] for job in jobs}
        for future in as_completed(futures):
            repo = futures[future]
            try:
                counts = future.result()
            except Exception as exc:  # one broken repository must not stop the others
                print(f"{repo}: FAILED {type(exc).__name__}: {exc}", flush=True)
                continue
            for key, value in counts.items():
                totals[key] += value
            print(f"{repo}: {counts}", flush=True)
    print(f"Done: {totals}")
    return 0


def build_repository(repo: str, clones: str, output: str, per_repo: int, since: str, horizon: int,
                     threshold: float, settings: dict) -> dict[str, int]:
    clone = Path(clones) / repo.replace("/", "__")
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(clone)], check=True)
    output_root = Path(output)
    observed_until = last_commit_time(clone)
    start = datetime.fromisoformat(since)
    eligible = [pr for pr in merged_prs_from_history(clone)
                if datetime.fromisoformat(pr.merged_at) >= start
                and future_moment(pr.merged_at, horizon) <= observed_until.astimezone(timezone.utc)]
    chosen = _evenly(eligible, per_repo * 2)        # extra candidates: some will be skipped
    snapshots = Snapshotter(clone, Path(clones) / "_worktrees" / repo.replace("/", "__"))
    cache = output_root / "_future_summaries" / repo.replace("/", "__")
    log_path = output_root / "build_log.jsonl"
    counts = {"built": 0, "skipped": 0, "existing": 0, "failed": 0}
    for pr in chosen:
        if counts["built"] + counts["existing"] >= per_repo:
            break
        sample_dir = output_root / repo.replace("/", "__") / str(pr.number)
        if (sample_dir / "metadata.json").is_file():
            counts["existing"] += 1
            continue
        started = time.perf_counter()
        entry = {"repo": repo, "pr_number": pr.number, "merged_at": pr.merged_at}
        try:
            metadata = build_coupling_sample(repo, pr, snapshots, output_root, cache, settings,
                                             horizon_months=horizon, threshold=threshold)
            entry.update({"status": "built", "label": metadata["label"], "reason": metadata["label_reason"]})
            counts["built"] += 1
        except SampleSkipped as exc:
            entry.update({"status": "skipped", "reason": str(exc)})
            counts["skipped"] += 1
        except Exception as exc:  # keep going; the log says what broke
            entry.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:300]})
            counts["failed"] += 1
        entry["seconds"] = round(time.perf_counter() - started, 2)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    return counts


def _evenly(items: list, count: int) -> list:
    """Take ``count`` items spread evenly over the list (deterministic, covers the whole time span)."""
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[int(index * step)] for index in range(count)]


if __name__ == "__main__":
    raise SystemExit(main())
