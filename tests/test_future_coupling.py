"""Automatic future-coupling labels, PR discovery from Git history, and the v5 sample builder."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.dataset.future_coupling import (
    coupling_summary, future_coupling_label, module_dependency_adjacency, node_delta_features, touched_module_names,
)
from src.dataset.pr_history import merged_prs_from_history, production_python_files

SETTINGS = {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", "docs"], "excluded_file_names": ["setup.py"]}


def graph_of(root: Path, files: dict[str, str]) -> dict:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return build_dependency_graph(extract_repository_ast(root, SETTINGS))


def summary(modules: dict[str, tuple[int, int]], cyclic=(), path_prefix="") -> dict:
    count = len(modules)
    edges = sum(ce for _, ce in modules.values())
    return {"module_count": count, "edge_count": edges, "mean_coupling": 2 * edges / count if count else 0.0,
            "modules": {name: {"path": f"{path_prefix}{name}.py", "ca": ca, "ce": ce}
                        for name, (ca, ce) in modules.items()},
            "cyclic_modules": list(cyclic)}


# --- module coupling ---------------------------------------------------------------------------

def test_every_dependency_kind_links_modules_but_containment_and_self_links_do_not(tmp_path):
    graph = graph_of(tmp_path, {
        "a.py": "import b\nfrom c import Base\nfrom d import LIMIT\n\nclass A(Base):\n    def run(self):\n"
                "        b.helper()\n        return LIMIT\n\ndef local():\n    return local\n",
        "b.py": "def helper():\n    return 1\n",
        "c.py": "class Base:\n    pass\n",
        "d.py": "LIMIT = 3\n",
    })
    adjacency = module_dependency_adjacency(graph)
    assert adjacency["a"] == {"b", "c", "d"}
    assert adjacency["b"] == adjacency["c"] == adjacency["d"] == set()


def test_summary_counts_afferent_and_efferent_coupling_and_import_cycles(tmp_path):
    graph = graph_of(tmp_path, {"a.py": "import b\n", "b.py": "import a\n", "c.py": "import a\n"})
    result = coupling_summary(graph)
    assert result["modules"]["a"] == {"path": "a.py", "ca": 2, "ce": 1}
    assert result["cyclic_modules"] == ["a", "b"]
    assert result["mean_coupling"] == pytest.approx(2 * 3 / 3)


def test_touched_modules_come_from_changed_paths():
    assert touched_module_names(summary({"pkg.a": (0, 0), "pkg.b": (0, 0)}, path_prefix=""), ["pkg.a.py"]) == ["pkg.a"]


# --- the label ---------------------------------------------------------------------------------

def test_coupling_growth_faster_than_the_project_trend_is_degrading():
    at_merge = summary({"a": (1, 1), "b": (1, 1), "c": (0, 0)})
    future = summary({"a": (2, 3), "b": (1, 1), "c": (0, 0)})       # a gained 3 links (2 -> 5)
    result = future_coupling_label(at_merge, future, ["a"], threshold=0.5)
    # mean coupling = 2 * edges / modules: 2*2/3 at merge, 2*4/3 later, so the trend is 4/3
    assert result["coupling_growth"] == 3 and result["repository_trend"] == pytest.approx(4 / 3)
    assert result["excess_growth"] == pytest.approx(3 - 4 / 3)
    assert result["label"] == 1 and result["reason"] == "excess_coupling_growth"


def test_growing_with_the_project_is_not_degrading():
    at_merge = summary({"a": (1, 1), "b": (1, 1)})
    future = summary({"a": (2, 2), "b": (2, 2)})                     # everything grew equally
    result = future_coupling_label(at_merge, future, ["a"], threshold=0.5)
    assert result["excess_growth"] == pytest.approx(0.0) and result["label"] == 0


def test_joining_a_new_cycle_is_degrading_even_without_growth():
    at_merge = summary({"a": (1, 1), "b": (1, 1)})
    future = summary({"a": (1, 1), "b": (1, 1)}, cyclic=["a", "b"])
    result = future_coupling_label(at_merge, future, ["a"], threshold=5.0)
    assert result["label"] == 1 and result["joined_cycle"] == ["a"]


def test_no_label_when_the_touched_modules_are_gone_later():
    result = future_coupling_label(summary({"a": (0, 0)}), summary({"z": (0, 0)}), ["a"], threshold=0.5)
    assert result["label"] is None and result["reason"] == "touched_modules_missing_in_future"


def test_delta_features_mark_new_nodes_and_gained_and_lost_dependency_edges(tmp_path):
    before = graph_of(tmp_path / "before", {"a.py": "import b\n\ndef run():\n    return 1\n", "b.py": "X = 1\n"})
    after = graph_of(tmp_path / "after", {"a.py": "import c\n\ndef run():\n    return 1\n\ndef extra():\n    return 2\n",
                                          "b.py": "X = 1\n", "c.py": "Y = 2\n"})
    deltas = node_delta_features(before, after)
    assert deltas["a.py:a"] == (0, 1, 1)              # gained import c, lost import b
    assert deltas["a.py:a.extra"] == (1, 0, 0)        # new function
    assert deltas["a.py:a.run"] == (0, 0, 0)


# --- PRs from Git history ----------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def commit(repo: Path, files: dict[str, str], message: str, date: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True,
                   env={**__import__("os").environ, **env})


@pytest.fixture
def history_repo(tmp_path) -> Path:
    repo = tmp_path / "clone"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    commit(repo, {"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n", "pkg/b.py": "X = 1\n"},
           "initial", "2021-01-05T10:00:00+00:00")
    commit(repo, {"pkg/a.py": "import pkg.b\n\ndef f():\n    return pkg.b.X\n"}, "Use b in a (#1)",
           "2021-02-10T10:00:00+00:00")
    commit(repo, {"tests/test_a.py": "def test():\n    pass\n"}, "Add tests (#2)", "2021-03-10T10:00:00+00:00")
    commit(repo, {"pkg/c.py": "import pkg.a\nimport pkg.b\n", "pkg/b.py": "import pkg.a\nX = 1\n"},
           "Grow coupling (#3)", "2021-06-10T10:00:00+00:00")
    commit(repo, {"pkg/d.py": "import pkg.a\n"}, "Later work", "2021-09-20T10:00:00+00:00")
    return repo


def test_squash_and_merge_subjects_give_pr_numbers_in_time_order(history_repo):
    prs = merged_prs_from_history(history_repo)
    assert [pr.number for pr in prs] == [1, 2, 3]
    assert prs[0].title == "Use b in a (#1)" and len(prs[0].before_sha) == 40


def test_test_docs_and_setup_files_are_not_production_code():
    paths = ["pkg/a.py", "tests/test_a.py", "pkg/test_b.py", "docs/conf.py", "setup.py", "README.md"]
    assert production_python_files(paths, {"docs"}, {"setup.py"}) == ["pkg/a.py"]


def test_builder_writes_a_labelled_sample_and_skips_test_only_prs(history_repo, tmp_path):
    pytest.importorskip("torch_geometric")
    from src.dataset.coupling_builder import SampleSkipped, Snapshotter, build_coupling_sample
    from src.ml.hetero_data import load_hetero_data
    prs = {pr.number: pr for pr in merged_prs_from_history(history_repo)}
    snapshots = Snapshotter(history_repo, tmp_path / "wt")
    out, cache = tmp_path / "samples", tmp_path / "cache"
    metadata = build_coupling_sample("o/r", prs[1], snapshots, out, cache, SETTINGS, horizon_months=6, threshold=0.5)
    # At merge a->b (a: ce 1, b: ca 1). By the end of 2021-08 b imports a (cycle a<->b) and c uses both.
    assert metadata["label"] == 1 and metadata["label_reason"] == "joined_new_cycle"
    label = json.loads((out / "o__r/1/label.json").read_text())
    assert label["pr_creates_cycle"] == 0 and label["joined_cycle"] == ["pkg.a"]
    data = load_hetero_data(out / "o__r/1/graph.pt")
    assert data.delta_feature_names == ["is_new_in_pr", "dependency_edges_gained", "dependency_edges_lost"]
    assert bool(data["module"].touched_mask.any()) and data["module"].delta.shape[1] == 3
    assert (out / "o__r/1/diff.patch").read_text().startswith("diff --git a/pkg/a.py")
    assert json.loads((out / "o__r/1/metrics.json").read_text())["delta"]["internal_import_edge_count"] == 1
    with pytest.raises(SampleSkipped, match="no production Python change"):
        build_coupling_sample("o/r", prs[2], snapshots, out, cache, SETTINGS, horizon_months=6, threshold=0.5)


def test_snapshotter_works_with_relative_paths(history_repo, tmp_path, monkeypatch):
    """The build is usually run as ``--clones data/repositories`` (relative); the worktree must
    still be created where the snapshotter later looks for it."""
    from src.dataset.coupling_builder import Snapshotter
    monkeypatch.chdir(tmp_path)
    snapshots = Snapshotter(history_repo.relative_to(tmp_path), Path("wt_rel") / "o__r")
    head = git(history_repo, "rev-parse", "HEAD").strip()
    assert (snapshots.checkout(head) / "pkg" / "a.py").is_file()
    assert (tmp_path / "wt_rel" / "o__r" / ".git").exists()


def test_rebuild_keeps_the_label_and_refreshes_the_graph(history_repo, tmp_path):
    pytest.importorskip("torch_geometric")
    from src.dataset.coupling_builder import Snapshotter, build_coupling_sample, rebuild_sample_graph
    from src.ml.coupling_data import discover_coupling_samples
    prs = {pr.number: pr for pr in merged_prs_from_history(history_repo)}
    snapshots = Snapshotter(history_repo, tmp_path / "wt")
    out, cache = tmp_path / "samples", tmp_path / "cache"
    build_coupling_sample("o/r", prs[1], snapshots, out, cache, SETTINGS, horizon_months=6, threshold=0.5)
    [record] = discover_coupling_samples(out)
    graph_file = out / "o__r/1/graph.pt"
    graph_file.write_bytes(b"stale")
    result = rebuild_sample_graph(record, snapshots, cache, SETTINGS, "test-extractor")
    assert result["status"] == "rebuilt" and graph_file.read_bytes() != b"stale"
    assert json.loads((out / "o__r/1/metadata.json").read_text())["extractor"] == "test-extractor"
    # A stored label that disagrees with the code is reported and nothing is written.
    tampered = dict(record, label=0, label_reason="no_degradation")
    graph_file.write_bytes(b"stale")
    result = rebuild_sample_graph(tampered, snapshots, cache, SETTINGS, "test-extractor")
    assert result["status"] == "label_changed" and graph_file.read_bytes() == b"stale"
