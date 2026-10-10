"""Safe Git helpers for reconstructing pull-request before/after snapshots.

This module does not build graphs.  It prepares detached source snapshots that the
existing Steps 2-5 pipeline can analyse without switching the stored clone's branch.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Iterator


_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class GitSnapshotError(RuntimeError):
    """A requested commit or temporary snapshot could not be prepared safely."""


@dataclass(frozen=True)
class CommitPair:
    """The two repository states represented by one merged pull request."""

    before_sha: str
    after_sha: str


def resolve_commit_pair(repository_path: str | Path, merge_commit_sha: str) -> CommitPair:
    """Return first-parent BEFORE and merge-commit AFTER SHAs.

    GitHub supplies a full merge commit SHA.  Its first parent is the target branch
    immediately before the pull request was integrated; the merge commit is the
    repository state immediately afterward.
    """
    repository = _repository(repository_path)
    merge_sha = _validated_sha(merge_commit_sha)
    line = _git(repository, "rev-list", "--parents", "-n", "1", merge_sha).strip()
    parts = line.split()
    if not parts or parts[0].lower() != merge_sha.lower():
        raise GitSnapshotError(f"Git did not resolve merge commit {merge_sha}")
    if len(parts) < 2:
        raise GitSnapshotError(f"Commit {merge_sha} has no first parent")
    return CommitPair(before_sha=parts[1], after_sha=parts[0])


@contextmanager
def detached_snapshot(repository_path: str | Path, commit_sha: str,
                      destination: str | Path) -> Iterator[Path]:
    """Temporarily check out one commit without changing the stored clone's branch."""
    repository = _repository(repository_path)
    sha = _validated_sha(commit_sha)
    target = Path(destination).resolve()
    if target.exists():
        raise GitSnapshotError(f"Snapshot destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(repository, "worktree", "add", "--detach", str(target), sha)
    try:
        yield target
    finally:
        result = _git_result(repository, "worktree", "remove", "--force", str(target))
        if result.returncode != 0:
            raise GitSnapshotError(
                f"Could not remove temporary worktree {target}: {result.stderr.strip()}"
            )


def write_python_diff(repository_path: str | Path, pair: CommitPair,
                      destination: str | Path) -> Path:
    """Write a stable, no-colour unified diff containing Python files only."""
    repository = _repository(repository_path)
    before = _validated_sha(pair.before_sha)
    after = _validated_sha(pair.after_sha)
    diff = _git(
        repository,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=3",
        before,
        after,
        "--",
        "*.py",
    )
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(diff, encoding="utf-8", newline="\n")
    return output


def _validated_sha(value: str) -> str:
    if not isinstance(value, str) or not _FULL_SHA.fullmatch(value):
        raise GitSnapshotError(f"Expected a full 40-character commit SHA, got {value!r}")
    return value.lower()


def _repository(repository_path: str | Path) -> Path:
    repository = Path(repository_path).resolve()
    if not repository.is_dir() or not (repository / ".git").exists():
        raise GitSnapshotError(f"Not a Git repository: {repository}")
    return repository


def _git(repository: Path, *arguments: str) -> str:
    result = _git_result(repository, *arguments)
    if result.returncode != 0:
        command = "git " + " ".join(arguments)
        raise GitSnapshotError(f"{command} failed: {result.stderr.strip()}")
    return result.stdout


def _git_result(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

