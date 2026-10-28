"""Dev-only stand-in for data/v5_manifest.jsonl, built from local Git history.

    python -m src.validation_v5.manifest_dev --repo pallets/flask=../validation_v5_sources/history/pallets__flask \
        --repo psf/requests=../validation_v5_sources/history/psf__requests --per-repo 10 \
        --out data/validation_v5/v5_manifest_dev.jsonl

A PR is a first-parent commit on the default branch whose subject is "Merge pull request #N"
or ends with "(#N)". before = its first parent; changed Python files exclude tests/, docs/
and examples/. ``split`` is "dev" and ``label`` is null: these rows have no outcome.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterator

_MERGE = re.compile(r"^Merge pull request #(\d+)\b")
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")
EXCLUDED_PARTS = {"tests", "test", "docs", "doc", "examples"}


def pr_number(subject: str) -> int | None:
    match = _MERGE.match(subject) or _SQUASH.search(subject)
    return int(match.group(1)) if match else None


def is_production_python(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return parts[-1].endswith(".py") and not EXCLUDED_PARTS.intersection(parts[:-1])


def module_name(path: str) -> str:
    """``src/flask/app.py`` -> ``flask.app``; ``pkg/__init__.py`` -> ``pkg``."""
    parts = path.replace("\\", "/")[:-3].split("/")
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def iter_pr_commits(repository: Path, branch: str = "HEAD") -> Iterator[dict[str, Any]]:
    log = _git(repository, "log", "--first-parent", "--format=%H%x1f%P%x1f%cI%x1f%s", branch)
    for line in log.splitlines():
        sha, parents, date, subject = line.split("\x1f", 3)
        number = pr_number(subject)
        if number is None or not parents:
            continue
        yield {"sha": sha, "before": parents.split()[0], "merged_at": date, "subject": subject, "number": number}


def build_rows(repository: Path, repo: str, limit: int, branch: str = "HEAD") -> list[dict[str, Any]]:
    rows = []
    for commit in iter_pr_commits(repository, branch):
        changed = _git(repository, "diff", "--name-only", "--no-renames", commit["before"], commit["sha"]).splitlines()
        python = sorted(path for path in changed if is_production_python(path))
        if not python:
            continue
        rows.append({"sample_id": f"{repo}#{commit['number']}", "repo": repo, "number": commit["number"],
                     "title": commit["subject"], "merged_at": commit["merged_at"],
                     "before_commit_sha": commit["before"], "merge_commit_sha": commit["sha"],
                     "changed_python_files": python, "touched_modules": sorted({module_name(p) for p in python}),
                     "split": "dev", "label": None})
        if len(rows) >= limit:
            break
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a small dev manifest from local Git history.")
    parser.add_argument("--repo", action="append", required=True, help="owner/name=path/to/full/clone")
    parser.add_argument("--per-repo", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("data/validation_v5/v5_manifest_dev.jsonl"))
    args = parser.parse_args(argv)
    rows = []
    for item in args.repo:
        repo, _, path = item.partition("=")
        rows += build_rows(Path(path), repo, args.per_repo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(f"{len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
