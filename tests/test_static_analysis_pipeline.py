from __future__ import annotations

from src.analysis.pipeline import analyse_repository


def test_pipeline_writes_graph_and_node_features(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "module.py").write_text(
        "import json\n\n"
        "def helper(value):\n    return value\n\n"
        "def caller(value):\n    return helper(value)\n",
        encoding="utf-8",
    )
    result = analyse_repository(repository, tmp_path / "output", {
        "include_tests": False, "max_python_files_per_repository": 10,
        "excluded_directory_names": [".git", "__pycache__"],
    })
    assert (tmp_path / "output" / "ast.json").is_file()
    assert (tmp_path / "output" / "dependency_graph.json").is_file()
    assert (tmp_path / "output" / "node_features.json").is_file()
    edges = result["graph"]["edges"]
    assert any(edge["type"] == "IMPORTS" for edge in edges)
    assert any(edge["type"] == "CALLS" and edge["target"].endswith("module.helper") for edge in edges)
    caller = next(record for record in result["features"]["nodes"] if record["node_id"].endswith("module.caller"))
    assert caller["features"]["parameter_count"] == 1
    assert caller["features"]["call_out_degree"] == 1
