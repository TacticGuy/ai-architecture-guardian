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
from typing import Any, Iterator


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

    This is an integration-commit diff, not proof of the whole PR's boundary.
    Multi-commit rebase integrations require additional verification. Future-risk
    datasets must use resolve_verified_commit_pair instead.
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


def verified_boundary(parents: list[str], head_ref_sha: object, commit_count: object) -> str:
    """Reject ambiguous multi-commit squash/rebase rather than use the last commit."""
    if len(parents) == 2 and isinstance(head_ref_sha, str) and parents[1] == head_ref_sha.lower():
        return "merge_head_verified"
    if len(parents) == 1 and type(commit_count) is int and commit_count == 1:
        return "single_commit_boundary"
    raise GitSnapshotError("PR integration boundary is unverified (multi-commit rebase/squash or head mismatch)")


def resolve_verified_commit_pair(repository_path: str | Path, record: dict[str, Any]) -> CommitPair:
    repository = _repository(repository_path)
    sha = _validated_sha(record.get("merge_commit_sha"))
    fields = _git(repository, "rev-list", "--parents", "-n", "1", sha).split()
    if not fields or fields[0] != sha:
        raise GitSnapshotError("PR integration commit could not be resolved")
    verified_boundary(fields[1:], record.get("head_ref_sha"), record.get("commit_count"))
    pair = CommitPair(before_sha=fields[1], after_sha=sha)
    supplied_before = record.get("before_commit_sha")
    if supplied_before is not None and supplied_before != pair.before_sha:
        raise GitSnapshotError("Label's before_commit_sha does not match the verified Git boundary")
    return pair


def parse_changed_files(output: str) -> list[dict[str, str | None]]:
    """Parse NUL-delimited name/status, keeping deletions and both rename paths."""
    fields = output.split("\0")
    if fields[-1] == "":
        fields.pop()
    changes = []
    index = 0
    while index < len(fields):
        status = fields[index]
        width = 3 if status.startswith(("R", "C")) else 2
        if not status or status[0] not in "ACDMRTUXB" or index + width > len(fields):
            raise GitSnapshotError("Malformed Git name/status output")
        old = fields[index + 1]
        new = fields[index + 2] if width == 3 else old
        changes.append({"status": status,
                        "before_path": None if status.startswith("A") else old,
                        "after_path": None if status.startswith("D") else new})
        index += width
    return changes


def changed_file_records(repository_path: str | Path, pair: CommitPair) -> list[dict[str, str | None]]:
    repository = _repository(repository_path)
    output = _git(repository, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z",
                  "--find-renames", _validated_sha(pair.before_sha), _validated_sha(pair.after_sha), "--")
    return parse_changed_files(output)


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
    # Historical repositories can contain paths beyond Windows' legacy MAX_PATH.
    # Apply this only to the temporary worktree command; no repository config is changed.
    _git(repository, "-c", "core.longpaths=true", "worktree", "add", "--detach", str(target), sha)
    try:
        yield target
    finally:
        result = _git_result(
            repository, "-c", "core.longpaths=true", "worktree", "remove", "--force", str(target)
        )
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
        "--no-textconv",
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


def changed_python_files(repository_path: str | Path, pair: CommitPair) -> list[str]:
    """Return Python paths including deleted files and both sides of renames."""
    return sorted({path for change in changed_file_records(repository_path, pair)
                   for path in (change["before_path"], change["after_path"])
                   if path and path.endswith(".py")})


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
