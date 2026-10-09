"""Point 5 script: scripts/build_pyg_graphs.py turns analysis folders into graph.pt files."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from src.analysis.pipeline import analyse_repository  # noqa: E402
from src.ml.hetero_data import load_hetero_data  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("build_pyg_graphs", ROOT / "scripts" / "build_pyg_graphs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_analysis(tmp_path) -> tuple[Path, dict]:
    repository = tmp_path / "repo"
    (repository / "pkg").mkdir(parents=True)
    (repository / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repository / "pkg" / "core.py").write_text(
        "import os\n\nclass Engine:\n    def run(self):\n        return os.getcwd()\n", encoding="utf-8")
    analysis = tmp_path / "analysis" / "example__repo"
    result = analyse_repository(repository, analysis, {
        "include_tests": False, "max_python_files_per_repository": 50, "excluded_directory_names": [".git"]})
    return analysis, result


def test_script_builds_a_loadable_graph_file(tmp_path, capsys):
    analysis, result = make_analysis(tmp_path)
    output = tmp_path / "pyg"
    assert load_script().main(["--analysis-dir", str(analysis), "--output-dir", str(output)]) == 0
    data = load_hetero_data(output / "example__repo" / "graph.pt")
    assert sum(data[node_type].num_nodes for node_type in data.node_types) == len(result["graph"]["nodes"])
    assert sum(data[edge_type].num_edges for edge_type in data.edge_types) == len(result["graph"]["edges"])
    printed = capsys.readouterr().out
    assert "Built example__repo" in printed and "module=2" in printed


def test_missing_analysis_gives_a_clear_message_and_failure_code(tmp_path, capsys):
    status = load_script().main(["--analysis-dir", str(tmp_path / "nothing_here"), "--output-dir", str(tmp_path / "pyg")])
    assert status == 1
    assert "run analyse_repositories.py first" in capsys.readouterr().out
    assert not (tmp_path / "pyg").exists()


def test_unknown_repository_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        load_script().main(["--repo", "nobody/nothing", "--output-dir", str(tmp_path / "pyg")])
