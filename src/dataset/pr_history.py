"""Find merged pull requests straight from a clone's Git history (no GitHub API needed).

GitHub writes the PR number into the commit that lands on the default branch:
``Merge pull request #123 from user/branch`` for merge commits and ``Title (#123)`` for
squash merges. Following first parents only keeps exactly the commits that landed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import subprocess

_MERGE = re.compile(r"^Merge pull request #(\d+) from ")
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")


@dataclass(frozen=True)
class MergedPR:
    number: int
    merge_sha: str          # the commit on the default branch (merge or squash commit)
    before_sha: str         # its first parent: the code just before the PR landed
    merged_at: str          # committer date, ISO 8601 with offset
    title: str


def merged_prs_from_history(repository: str | Path, ref: str = "HEAD") -> list[MergedPR]:
    """All PR landings on ``ref``'s first-parent line, oldest first, one per PR number."""
    output = _git(repository, "log", "--first-parent", "--format=%H%x09%P%x09%cI%x09%s", ref)
    found: dict[int, MergedPR] = {}
    for line in output.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        sha, parents, date, subject = parts
        match = _MERGE.match(subject) or _SQUASH.search(subject)
        parent_list = parents.split()
        if not match or not parent_list:
            continue
        number = int(match.group(1))
        # git log lists newest first; a PR number seen again further down is an older
        # commit that merely mentions it (e.g. a revert's subject), so keep the newest.
        found.setdefault(number, MergedPR(number, sha, parent_list[0], date, subject))
    return sorted(found.values(), key=lambda pr: (pr.merged_at, pr.number))


def production_python_files(paths: list[str], excluded_dirs: set[str], excluded_files: set[str]) -> list[str]:
    """Same rule as the static analysis: no tests, docs, examples, build scripts."""
    kept = []
    for path in paths:
        if not path.endswith(".py"):
            continue
        parts = PurePosixPath(path).parts
        if any(part in excluded_dirs for part in parts[:-1]) or parts[-1] in excluded_files:
            continue
        if any(part in {"tests", "test"} or part.startswith("test_") for part in parts):
            continue
        kept.append(path)
    return sorted(set(kept))


def changed_paths(repository: str | Path, before: str, after: str) -> list[str]:
    """Both sides of every changed path (renames included)."""
    output = _git(repository, "diff", "--name-status", "--no-renames", before, after)
    paths = []
    for line in output.splitlines():
        fields = line.split("\t")
        paths.extend(fields[1:])
    return sorted(set(paths))


def commit_at_or_before(repository: str | Path, moment: datetime, ref: str = "HEAD") -> str | None:
    """The last first-parent commit on ``ref`` committed at or before ``moment``."""
    sha = _git(repository, "rev-list", "-1", "--first-parent", f"--before={moment.isoformat()}", ref).strip()
    return sha or None


def last_commit_time(repository: str | Path, ref: str = "HEAD") -> datetime:
    return datetime.fromisoformat(_git(repository, "log", "-1", "--format=%cI", ref).strip())


def _git(repository: str | Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repository), *arguments], check=False, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout
