"""Mandatory 3: established code-quality tools on every v5 PR (fast, parallel, resumable).

    python scripts/run_tool_metrics_v5.py --manifest kaggle_v5_big/v5_manifest.jsonl \
        --clones data/repositories --output data/tool_metrics_v5.jsonl --workers 20

For each PR, the touched production files are read from Git (``git show``) at the commit before
the PR and at the merge commit (the PR applied, which a pre-merge tool would also see):

* radon    mean / max cyclomatic complexity, mean maintainability index, SLOC (after + change)
* pylint   score and message counts per category plus the R09xx design checks (after + change)
* hotspot  CodeScene-style hotspot (Tornhill's published method, re-implemented; CodeScene itself is
           commercial): how often the touched files changed in the 182 days before the PR, times
           their complexity. Only history before the PR is used.

Files are written to a temporary folder at their real relative paths, with ``__init__.py`` added
to every folder, so pylint sees them as package modules. Otherwise a project file named like a
standard-library module (aiohttp's ``abc.py`` doing ``from abc import ABC``) would import itself.
Each line: {"sample_id", "radon.*", "pylint.*", "hotspot.*"}; numbers, or null when a tool failed.
Re-running skips samples already in the output.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time

PYLINT_TIMEOUT = 180
DESIGN_PREFIX = "R09"          # too-many-* design checks: the closest pylint gets to coupling


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--clones", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--split", nargs="*", help="only these splits (train val test)")
    parser.add_argument("--limit", type=int, default=None, help="first N samples (smoke test)")
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.split:
        rows = [row for row in rows if row["split"] in set(args.split)]
    if args.limit:
        rows = rows[:args.limit]
    done = set()
    if args.output.is_file():
        done = {json.loads(line)["sample_id"] for line in args.output.read_text(encoding="utf-8").splitlines()
                if line.strip()}
    todo = [row for row in rows if row["sample_id"] not in done]
    print(f"{len(todo)} PRs to measure ({len(done)} already done)", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool, args.output.open("a", encoding="utf-8") as out:
        futures = [pool.submit(measure, row, str(args.clones)) for row in todo]
        for index, future in enumerate(as_completed(futures), 1):
            out.write(json.dumps(future.result()) + "\n")
            out.flush()
            if index % 100 == 0 or index == len(todo):
                rate = (time.perf_counter() - started) / index
                print(f"{index}/{len(todo)}  ~{rate * (len(todo) - index) / 60:.0f} min left", flush=True)
    meta = {"tools": _versions(), "manifest": str(args.manifest), "measured_at": datetime.now().isoformat(),
            "pylint_timeout_seconds": PYLINT_TIMEOUT, "hotspot_window_days": 182}
    args.output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return 0


def clone_path(clones: Path, repo: str) -> Path:
    """Accept both clone layouts: ``owner__name`` (dataset build) and ``owner/name``."""
    flat = clones / repo.replace("/", "__")
    return flat if flat.is_dir() else clones / repo


def measure(row: dict, clones: str) -> dict:
    clone = clone_path(Path(clones), row["repo"])
    files = row["changed_python_files"]
    after = {path: _show(clone, row["merge_commit_sha"], path) for path in files}
    before = {path: _show(clone, row["before_commit_sha"], path) for path in files}
    result: dict = {"sample_id": row["sample_id"]}
    now, then = radon_metrics(after), radon_metrics(before)
    result.update({f"radon.{key}": value for key, value in now.items()})
    result.update({f"radon.delta_{key}": _minus(now[key], then[key]) for key in now})
    lint_after, lint_before = pylint_metrics(after), pylint_metrics(before)
    result.update({f"pylint.{key}": value for key, value in lint_after.items()})
    result.update({f"pylint.delta_{key}": _minus(lint_after[key], lint_before[key]) for key in lint_after})
    result.update(hotspot_metrics(clone, row, now["mean_cc"]))
    return result


def _minus(a, b):
    return None if a is None or b is None else a - b


def _show(clone: Path, sha: str, path: str) -> str | None:
    completed = subprocess.run(["git", "-C", str(clone), "show", f"{sha}:{path}"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    return completed.stdout if completed.returncode == 0 else None   # None: file absent on that side


def radon_metrics(sources: dict[str, str | None]) -> dict[str, float]:
    from radon.complexity import cc_visit
    from radon.metrics import mi_visit
    from radon.raw import analyze
    complexities: list[int] = []
    indexes: list[float] = []
    sloc = 0
    for text in sources.values():
        if not text:
            continue
        try:
            complexities.extend(block.complexity for block in cc_visit(text))
            indexes.append(mi_visit(text, multi=True))
            sloc += analyze(text).sloc
        except Exception:  # radon cannot parse every file (e.g. newer syntax): skip that file
            continue
    return {"mean_cc": sum(complexities) / len(complexities) if complexities else 0.0,
            "max_cc": float(max(complexities, default=0)), "blocks": float(len(complexities)),
            "mean_mi": sum(indexes) / len(indexes) if indexes else 100.0, "sloc": float(sloc)}


def write_as_packages(root: Path, sources: dict[str, str | None]) -> list[str]:
    """Write files at their real relative paths and make every folder a package."""
    written = []
    for path, text in sources.items():
        if not text:
            continue
        target = root / PurePosixPath(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(str(target))
        folder = target.parent
        while folder != root:
            init = folder / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
            folder = folder.parent
    return written


def pylint_metrics(sources: dict[str, str | None]) -> dict[str, float | None]:
    keys = ("convention", "refactor", "warning", "error", "design")
    with tempfile.TemporaryDirectory() as folder:
        paths = write_as_packages(Path(folder), sources)
        if not paths:
            return {"score": 10.0, **{key: 0.0 for key in keys}, **{f"{key}_per_kloc": 0.0 for key in keys}}
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pylint", "--output-format=json2", "--persistent=n", "--jobs=1",
                 "--disable=import-error,no-name-in-module,cyclic-import", *paths],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PYLINT_TIMEOUT, cwd=folder)
            report = json.loads(completed.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return {"score": None, **{key: None for key in keys}, **{f"{key}_per_kloc": None for key in keys}}
    counts = dict.fromkeys(keys, 0)
    for message in report.get("messages", []):
        kind = message.get("type")
        if kind in counts:
            counts[kind] += 1
        if str(message.get("messageId", "")).startswith(DESIGN_PREFIX):
            counts["design"] += 1
    lines = sum(len((text or "").splitlines()) for text in sources.values()) or 1
    return {"score": float(report.get("statistics", {}).get("score", 10.0)),
            **{key: float(value) for key, value in counts.items()},
            **{f"{key}_per_kloc": 1000.0 * value / lines for key, value in counts.items()}}


def hotspot_metrics(clone: Path, row: dict, mean_cc: float) -> dict[str, float]:
    since = (datetime.fromisoformat(row["merged_at"]) - timedelta(days=182)).isoformat()
    changes = []
    for path in row["changed_python_files"]:
        log = subprocess.run(["git", "-C", str(clone), "log", "--first-parent", "--format=%H", f"--since={since}",
                              row["before_commit_sha"], "--", path], capture_output=True, text=True)
        changes.append(len(log.stdout.split()))
    total = float(sum(changes))
    return {"hotspot.change_frequency": total, "hotspot.max_change_frequency": float(max(changes, default=0)),
            "hotspot.score": total * mean_cc, "hotspot.files_changed_recently": float(sum(1 for c in changes if c))}


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version
    found = {}
    for name in ("radon", "pylint"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = "missing"
    return found


if __name__ == "__main__":
    raise SystemExit(main())
