from pathlib import Path
import subprocess

import pytest

from src.dataset.history_audit import (
    ancestry_masks, audit_repository, overlap_audit, parse_changes,
    read_blobs, reconstruction_status, source_facts, syntax_delta,
)
from src.dataset.git_snapshots import GitSnapshotError


def test_deleted_and_renamed_paths_are_preserved_without_line_splitting():
    changes = parse_changes(b"D\0pkg/old.py\0R100\0pkg/with space.py\0pkg/new\nname.py\0A\0notes.txt\0")
    assert changes[0] == {"status": "D", "before_path": "pkg/old.py", "after_path": None}
    assert changes[1]["before_path"] == "pkg/with space.py"
    assert changes[1]["after_path"] == "pkg/new\nname.py"
    assert changes[2]["before_path"] is None
    with pytest.raises(ValueError, match="Malformed"):
        parse_changes(b"R100\0old.py\0")


def test_import_evidence_ignores_comments_and_does_not_execute_source():
    source = b"# import invented\nfrom .service import run\nraise RuntimeError('must not execute')\n"
    assert source_facts(source)["imports"] == ["from .service import run"]
    delta = syntax_delta(b"import old\n", b"import new\n")
    assert delta["added_imports"] == ["import new"]
    assert delta["removed_imports"] == ["import old"]


def test_encoding_and_parse_errors_are_not_silently_treated_as_empty():
    assert source_facts(b"# coding: latin-1\nNAME = 'caf\xe9'\n")["status"] == "parsed"
    assert syntax_delta(b"import old\n", b"def broken(")["status"] == "unresolved"
    assert source_facts(b"x" * (512 * 1024 + 1))["status"] == "source_too_large"


def test_commit_boundary_does_not_guess_squash_from_multicommit_metadata():
    assert reconstruction_status(["base", "head"], "head", 5) == "merge_head_verified"
    assert reconstruction_status(["base"], "head", 1) == "single_commit_boundary"
    assert reconstruction_status(["base"], "head", 5) == "ambiguous_squash_or_rebase"
    assert reconstruction_status(["base"], "head", None) == "ambiguous_squash_or_rebase"
    assert reconstruction_status(["base", "different"], "head", 1) == "merge_head_needs_verification"


def test_dag_ancestry_handles_branch_renaming_but_rejects_parallel_release():
    parents, masks = ancestry_masks("later early\nrelease base\nearly base\nbase\n", ["early", "later", "release"])
    assert parents["later"] == ["early"]
    rows = [
        {"sample_id": "r#1", "merged_at": "2024-01-01T00:00:00Z", "after_sha": "early", "base_ref_name": "master", "production_python_files": ["a.py"]},
        {"sample_id": "r#2", "merged_at": "2024-02-01T00:00:00Z", "after_sha": "later", "base_ref_name": "main", "production_python_files": ["a.py"]},
        {"sample_id": "r#3", "merged_at": "2024-03-01T00:00:00Z", "after_sha": "release", "base_ref_name": "1.x", "production_python_files": ["a.py"]},
    ]
    audit = overlap_audit(rows, masks)
    assert audit["counts"]["date_and_path_pairs"] == 3
    assert audit["counts"]["ancestor_pairs"] == 1
    assert audit["counts"]["unrelated_lineage_pairs"] == 2
    assert audit["counts"]["different_branch_but_ancestor_pairs"] == 1


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, encoding="utf-8").stdout.strip()


def test_real_git_audit_includes_deletion_and_preserves_checkout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Audit Test")
    git(repo, "config", "user.email", "audit@example.test")
    (repo / "old.py").write_text("import sys\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "rm", "old.py")
    (repo / "new.py").write_text("import os\nVALUE = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "unimportant title")
    head = git(repo, "rev-parse", "HEAD")
    records = [{"repo": "org/repo", "pr_number": 1, "merge_commit_sha": head,
                "commit_count": 1, "changed_files": 2, "base_ref_name": "main",
                "merged_at": "2024-01-01T00:00:00Z"}]
    rows, summary = audit_repository(repo, records, {}, "2024-12-31T00:00:00Z")
    assert rows[0]["production_python_files"] == ["new.py", "old.py"]
    assert rows[0]["label"] is None
    assert rows[0]["file_count_matches_metadata"]
    assert summary["production_prs_with_deletions"] == 1
    assert summary["diff_review_candidates"] == ["org/repo#1"]
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "branch", "--show-current") == "main"


def test_duplicate_ids_and_missing_commits_fail_closed(tmp_path):
    duplicate = {"repo": "r/r", "pr_number": 1}
    with pytest.raises(ValueError, match="Duplicate"):
        audit_repository(tmp_path, [duplicate, duplicate], {}, "2024-12-01T00:00:00Z")
    with pytest.raises(ValueError, match="timezone"):
        audit_repository(tmp_path, [duplicate], {}, "2024-12-01")


def test_partial_clone_is_detected_before_any_source_read(tmp_path, monkeypatch):
    calls = []

    def fake_git(repository, *args):
        calls.append(args)
        if args == ("rev-parse", "--is-shallow-repository"):
            return b"false\n"
        if args == ("rev-list", "--objects", "--missing=print", "--all"):
            return b"?missing-object\n"
        pytest.fail("Should stop before trying to read missing sources")

    monkeypatch.setattr("src.dataset.history_audit.git_bytes", fake_git)
    with pytest.raises(GitSnapshotError, match="lacks 1 reachable objects"):
        audit_repository(tmp_path, [{"repo": "org/repo", "pr_number": 1}], {}, "2024-12-01T00:00:00Z")
    assert len(calls) == 2


def test_batch_reader_handles_binary_newlines_and_missing_blob(tmp_path, monkeypatch):
    def fake_run(arguments, **kwargs):
        assert kwargs["input"] == b"sha:line\nname.py\0"
        return subprocess.CompletedProcess(arguments, 0, b"oid blob 4\na\x00b\n\n", b"")

    monkeypatch.setattr("src.dataset.history_audit.subprocess.run", fake_run)
    assert read_blobs(tmp_path, ["sha:line\nname.py", "sha:line\nname.py"]) == {"sha:line\nname.py": b"a\x00b\n"}
    monkeypatch.setattr("src.dataset.history_audit.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"missing missing\n", b""))
    with pytest.raises(GitSnapshotError, match="Unable to read"):
        read_blobs(tmp_path, ["sha:missing.py"])
