"""Live PR modes A-D against a local bare "origin" with fake refs/pull/N/{head,merge} refs (no network)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from src.live_pr import LivePRError, PRReference, prepare_repository

NUMBER = 7
REFERENCE = PRReference("o", "r", NUMBER)


class Origin:
    """A bare origin plus a scratch clone used to write commits and push refs into it."""

    def __init__(self, root: Path):
        self.bare = root / "origin.git"
        self.work = root / "dev"
        self.clock = 1_700_000_000
        git(root, "init", "--bare", "-b", "main", str(self.bare))
        git(root, "clone", self.bare.as_uri(), str(self.work))
        self.commit("pkg/a.py", "A = 1\n", "init")
        self.commit("pkg/b.py", "B = 1\n", "add b")
        self.push("main", "refs/heads/main")

    def run(self, *arguments: str, date: int | None = None) -> str:
        return git(self.work, *arguments, date=date)

    def commit(self, path: str, text: str, message: str, author_date: int | None = None) -> str:
        self.clock += 60
        file = self.work / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        self.run("add", path)
        self.run("commit", "-m", message, date=author_date or self.clock)
        return self.sha("HEAD")

    def merge(self, branch: str, *, squash: bool = False) -> str:
        self.clock += 60
        if squash:
            self.run("merge", "--squash", branch)
            self.run("commit", "-m", f"Squash #{NUMBER}", date=self.clock)
        else:
            self.run("merge", "--no-ff", "-m", f"Merge pull request #{NUMBER}", branch, date=self.clock)
        return self.sha("HEAD")

    def sha(self, revision: str) -> str:
        return self.run("rev-parse", revision).strip()

    def push(self, revision: str, ref: str) -> None:
        self.run("push", "-f", "origin", f"{revision}:{ref}")

    def clone(self, root: Path) -> Path:
        target = root / "clone"
        git(root, "clone", self.bare.as_uri(), str(target))
        return target


def git(cwd: Path, *arguments: str, date: int | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}
    if date is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{date} +0000"
    result = subprocess.run(["git", "-C", str(cwd), *arguments], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout


def api(origin: Origin, head: str, *, state: str = "open", merged: bool = False,
        merge_commit_sha: str | None = None, base_sha: str | None = None, commits: int = 1) -> dict:
    """The fields of fetch_pr's output that prepare_repository reads."""
    return {"sample_id": REFERENCE.sample_id, "repo": "o/r", "pr_number": NUMBER, "state": state,
            "merged": merged, "merge_commit_sha": merge_commit_sha, "commit_count": commits,
            "base_ref": "main", "base_sha": base_sha or origin.sha("origin/main"), "head_sha": head,
            "clone_url": origin.bare.as_uri()}


def feature(origin: Origin, *changes: tuple[str, str]) -> str:
    """Branch ``feature`` from main with one commit per change; push it as refs/pull/N/head."""
    origin.run("checkout", "-q", "-B", "feature", "main")
    for path, text in changes:
        head = origin.commit(path, text, f"change {path}")
    origin.push("feature", f"refs/pull/{NUMBER}/head")
    origin.run("checkout", "-q", "main")
    return head


def test_mode_a_test_merge_with_matching_base(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    base = origin.sha("main")
    origin.run("checkout", "-q", "--detach", "main")
    test_merge = origin.merge("feature")
    origin.push(test_merge, f"refs/pull/{NUMBER}/merge")
    pr = api(origin, head, base_sha=base)
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert (pr["mode"], pr["analysis_base_sha"], pr["analysis_after_sha"]) == ("open_test_merge", base, test_merge)
    assert "base_note" not in pr


def test_mode_a_stale_base_uses_the_test_merge_parent(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    old_base = origin.sha("main")
    origin.run("checkout", "-q", "--detach", "main")
    test_merge = origin.merge("feature")
    origin.push(test_merge, f"refs/pull/{NUMBER}/merge")
    origin.run("checkout", "-q", "main")
    new_base = origin.commit("pkg/c.py", "C = 1\n", "main moves on")
    origin.push("main", "refs/heads/main")
    pr = api(origin, head, base_sha=new_base)
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert pr["analysis_base_sha"] == old_base
    assert pr["analysis_after_sha"] == test_merge
    assert pr["api_base_sha"] == new_base
    assert pr["base_note"] == "GitHub test merge was computed against an older base"


def test_mode_b_merge_commit(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    before = origin.sha("main")
    merge = origin.merge("feature")
    origin.push("main", "refs/heads/main")
    pr = api(origin, head, state="closed", merged=True, merge_commit_sha=merge)
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert (pr["mode"], pr["merge_method"]) == ("merged_pr", "merge")
    assert (pr["analysis_base_sha"], pr["analysis_after_sha"]) == (before, merge)


def test_mode_b_squash_commit(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"), ("pkg/a.py", "A = 2\n"))
    before = origin.sha("main")
    squash = origin.merge("feature", squash=True)
    origin.push("main", "refs/heads/main")
    pr = api(origin, head, state="closed", merged=True, merge_commit_sha=squash, commits=2)
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert (pr["merge_method"], pr["analysis_base_sha"], pr["analysis_after_sha"]) == ("squash", before, squash)


def test_mode_b_rebase_merge_walks_back_over_every_pr_commit(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"), ("pkg/a.py", "A = 2\n"))
    before = origin.sha("main")
    origin.run("cherry-pick", "feature~1", "feature")  # keeps each commit's author and author date
    rebased = origin.sha("HEAD")
    origin.push("main", "refs/heads/main")
    pr = api(origin, head, state="closed", merged=True, merge_commit_sha=rebased, commits=2)
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert (pr["merge_method"], pr["analysis_base_sha"], pr["analysis_after_sha"]) == ("rebase", before, rebased)


def test_mode_b_rejects_a_merge_commit_that_is_not_on_the_base_branch(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    pr = api(origin, head, state="closed", merged=True, merge_commit_sha=head)
    origin.run("checkout", "-q", "feature")
    with pytest.raises(LivePRError, match="not on the base branch"):
        prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))


def test_mode_c_conflict_gives_a_clear_error_and_cleans_up(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 'feature'\n"))
    origin.commit("pkg/b.py", "B = 'main'\n", "conflicting change on main")
    origin.push("main", "refs/heads/main")
    clone = origin.clone(tmp_path)
    with pytest.raises(LivePRError, match="This PR has merge conflicts with main; GitHub cannot build a "
                                          "pre-merge state"):
        prepare_repository(api(origin, head), REFERENCE, tmp_path / "cache", clone)
    assert git(clone, "worktree", "list").count("\n") == 1  # only the main worktree is left


def test_mode_c_clean_local_merge_is_reproducible(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    base = origin.commit("pkg/c.py", "C = 1\n", "unrelated change on main")
    origin.push("main", "refs/heads/main")
    clone = origin.clone(tmp_path)
    first, second = api(origin, head), api(origin, head)
    prepare_repository(first, REFERENCE, tmp_path / "cache", clone)
    prepare_repository(second, REFERENCE, tmp_path / "cache", clone)
    assert (first["mode"], first["analysis_base_sha"]) == ("open_local_merge", base)
    assert first["analysis_after_sha"] == second["analysis_after_sha"]
    assert git(clone, "rev-list", "--parents", "-n", "1", first["analysis_after_sha"]).split()[1:] == [base, head]


def test_mode_d_closed_unmerged_uses_the_merge_base(tmp_path):
    origin = Origin(tmp_path)
    head = feature(origin, ("pkg/b.py", "B = 2\n"))
    fork_point = origin.sha("main")
    origin.commit("pkg/c.py", "C = 1\n", "main moves on")
    origin.push("main", "refs/heads/main")
    pr = api(origin, head, state="closed")
    prepare_repository(pr, REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
    assert (pr["mode"], pr["analysis_base_sha"], pr["analysis_after_sha"]) == ("closed_unmerged", fork_point, head)
    assert "closed without merging" in pr["mode_warning"]


def test_v5_node_and_edge_types_are_removed_for_an_older_checkpoint():
    import torch
    from torch_geometric.data import HeteroData

    from src.live_pr import _fit_to_checkpoint_schema

    graph = HeteroData()
    for node_type in ("module", "function", "global_variable"):
        graph[node_type].x = torch.zeros(2, 3)
    graph["module", "CONTAINS", "function"].edge_index = torch.tensor([[0], [1]])
    graph["module", "CONTAINS", "global_variable"].edge_index = torch.tensor([[0], [0]])
    graph["function", "ACCESSES_GLOBAL", "global_variable"].edge_index = torch.tensor([[1], [0]])
    checkpoint = {"metadata": (["module", "function"], [("module", "CONTAINS", "function")])}
    trimmed, dropped = _fit_to_checkpoint_schema(graph, checkpoint)
    assert trimmed.node_types == ["module", "function"]
    assert trimmed.edge_types == [("module", "CONTAINS", "function")]
    assert dropped == ["ACCESSES_GLOBAL", "global_variable"]  # CONTAINS is known, so not reported


def test_head_mismatch_is_rejected(tmp_path):
    origin = Origin(tmp_path)
    feature(origin, ("pkg/b.py", "B = 2\n"))
    with pytest.raises(LivePRError, match="head ref does not match"):
        prepare_repository(api(origin, "f" * 40), REFERENCE, tmp_path / "cache", origin.clone(tmp_path))
