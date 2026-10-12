from pathlib import Path
import subprocess

from src.dataset.history_matching import HistoryMatcher


SETTINGS = {"include_tests": False, "excluded_directory_names": [".git"],
            "excluded_file_names": []}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def setup(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "History test")
    git(repo, "config", "user.email", "history@example.test")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "service.py").write_text("VALUE = 0\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def merge_pr(repo: Path, number: int, base_sha: str | None = None,
             path: str = "pkg/service.py", source: str = "VALUE = 1\n") -> dict:
    branch = f"pr-{number}"
    git(repo, "switch", "-c", branch, base_sha or "main")
    target = repo / Path(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"change {number}")
    head = git(repo, "rev-parse", "HEAD")
    target_branch = "release" if base_sha is not None else "main"
    git(repo, "switch", target_branch)
    git(repo, "merge", "--no-ff", branch, "-m", f"merge {number}")
    sha = git(repo, "rev-parse", "HEAD")
    count = int(git(repo, "diff", "--name-only", f"{sha}^1", sha).count("\n") + bool(
        git(repo, "diff", "--name-only", f"{sha}^1", sha)))
    return {"repo": "org/repo", "pr_number": number, "pr_id": f"org/repo#{number}",
            "merge_commit_sha": sha, "head_ref_sha": head, "commit_count": 1,
            "changed_files": count,
            "merged_at": f"2024-0{number}-01T00:00:00Z"}


def test_matches_only_same_ancestral_path_and_attaches_evidence(tmp_path):
    repo, _ = setup(tmp_path)
    sample = merge_pr(repo, 1, source="VALUE = 1\n")
    event = merge_pr(repo, 2, source="VALUE = 2\n")
    matcher = HistoryMatcher(repo, [sample, event], SETTINGS)
    result = matcher.match(sample, event, set(matcher.files[sample["pr_id"]]),
                           set(matcher.files[event["pr_id"]]))
    assert result["status"] == "verified"
    assert result["matched_python_files"] == ["pkg/service.py"]
    assert result["history_evidence"]["ancestry_verified"]
    assert result["history_evidence"]["file_identity"] == "unchanged_paths"


def test_same_path_change_on_parallel_release_branch_is_not_a_match(tmp_path):
    repo, base = setup(tmp_path)
    sample = merge_pr(repo, 1, source="VALUE = 1\n")
    git(repo, "switch", "-c", "release", base)
    event = merge_pr(repo, 2, base_sha=base, source="VALUE = 2\n")
    matcher = HistoryMatcher(repo, [sample, event], SETTINGS)
    result = matcher.match(sample, event, set(matcher.files[sample["pr_id"]]),
                           set(matcher.files[event["pr_id"]]))
    assert result["status"] == "unrelated_lineage"


def test_rename_in_intervening_history_makes_file_identity_unknown(tmp_path):
    repo, _ = setup(tmp_path)
    sample = merge_pr(repo, 1, source="VALUE = 1\n")
    git(repo, "switch", "main")
    git(repo, "mv", "pkg/service.py", "pkg/renamed.py")
    git(repo, "commit", "-m", "move module")
    event = merge_pr(repo, 2, path="pkg/renamed.py", source="VALUE = 2\n")
    matcher = HistoryMatcher(repo, [sample, event], SETTINGS)
    result = matcher.match(sample, event, set(matcher.files[sample["pr_id"]]),
                           set(matcher.files[event["pr_id"]]))
    assert result["status"] == "uncertain_file_identity"


def test_machine_negative_is_limited_to_executable_ast_equivalence(tmp_path):
    repo, _ = setup(tmp_path)
    event = merge_pr(repo, 1, source='"""Old documentation."""\nVALUE = 1\n')
    git(repo, "switch", "main")
    git(repo, "switch", "-c", "pr-1-new")
    (repo / "pkg" / "service.py").write_text('"""New documentation."""\nVALUE = 1\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "change documentation")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "main")
    git(repo, "merge", "--no-ff", "pr-1-new", "-m", "merge doc-only edit")
    sha = git(repo, "rev-parse", "HEAD")
    doc_pr = {"repo": "org/repo", "pr_number": 2, "pr_id": "org/repo#2",
              "merge_commit_sha": sha, "head_ref_sha": head, "commit_count": 1,
              "changed_files": 1, "merged_at": "2024-02-01T00:00:00Z"}
    matcher = HistoryMatcher(repo, [event, doc_pr], SETTINGS)
    reviews = matcher.non_executable_reviews()
    assert [review["sample_id"] for review in reviews] == ["org/repo#2"]
    assert reviews[0]["review_kind"] == "machine_check_not_human_expert"
