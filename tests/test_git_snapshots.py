from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from src.dataset.git_snapshots import (
    GitSnapshotError,
    detached_snapshot,
    resolve_commit_pair,
    write_python_diff,
)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def merged_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Dataset Test")
    git(repository, "config", "user.email", "dataset@example.test")

    (repository / "module.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    git(repository, "add", "module.py")
    git(repository, "commit", "-m", "base")

    git(repository, "switch", "-c", "feature")
    (repository / "module.py").write_text("VALUE = 'feature'\n", encoding="utf-8")
    (repository / "notes.txt").write_text("not Python\n", encoding="utf-8")
    git(repository, "add", "module.py", "notes.txt")
    git(repository, "commit", "-m", "feature")

    git(repository, "switch", "main")
    (repository / "main.txt").write_text("main branch\n", encoding="utf-8")
    git(repository, "add", "main.txt")
    git(repository, "commit", "-m", "main work")
    before_sha = git(repository, "rev-parse", "HEAD")

    git(repository, "merge", "--no-ff", "feature", "-m", "merge feature")
    merge_sha = git(repository, "rev-parse", "HEAD")
    return repository, before_sha, merge_sha


def test_resolves_first_parent_and_keeps_main_checkout_unchanged(tmp_path):
    repository, expected_before, merge_sha = merged_repository(tmp_path)
    pair = resolve_commit_pair(repository, merge_sha)
    original_branch = git(repository, "branch", "--show-current")

    with detached_snapshot(repository, pair.before_sha, tmp_path / "before") as before:
        assert (before / "module.py").read_text(encoding="utf-8") == "VALUE = 'base'\n"
    with detached_snapshot(repository, pair.after_sha, tmp_path / "after") as after:
        assert (after / "module.py").read_text(encoding="utf-8") == "VALUE = 'feature'\n"

    assert pair.before_sha == expected_before
    assert pair.after_sha == merge_sha
    assert git(repository, "branch", "--show-current") == original_branch == "main"
    assert not (tmp_path / "before").exists()
    assert not (tmp_path / "after").exists()


def test_writes_python_only_unified_diff(tmp_path):
    repository, _, merge_sha = merged_repository(tmp_path)
    pair = resolve_commit_pair(repository, merge_sha)

    output = write_python_diff(repository, pair, tmp_path / "sample" / "diff.patch")
    diff = output.read_text(encoding="utf-8")

    assert "module.py" in diff
    assert "VALUE = 'feature'" in diff
    assert "notes.txt" not in diff


def test_rejects_non_sha_input(tmp_path):
    repository, _, _ = merged_repository(tmp_path)
    with pytest.raises(GitSnapshotError, match="40-character"):
        resolve_commit_pair(repository, "HEAD")

