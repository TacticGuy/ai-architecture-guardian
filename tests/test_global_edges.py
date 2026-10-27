"""Shared global state: module-level variables become nodes, and functions that read or
write them get ACCESSES_GLOBAL edges (the fourth relation type in the proposal)."""
from __future__ import annotations

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.analysis.features import create_node_features


def settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__"]}


def graph_of(tmp_path, files: dict[str, str]) -> dict:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return build_dependency_graph(extract_repository_ast(tmp_path, settings()))


def accesses(graph: dict) -> set[tuple[str, str]]:
    names = {node["id"]: node["qualified_name"] for node in graph["nodes"]}
    return {(names[edge["source"]], names[edge["target"]]) for edge in graph["edges"]
            if edge["type"] == "ACCESSES_GLOBAL"}


def test_module_variables_become_nodes_contained_by_their_module(tmp_path):
    graph = graph_of(tmp_path, {"app.py": "import os\nCOUNT = 0\nLIMIT: int = 5\nA, B = 1, 2\n"
                                          "__all__ = ['run']\n\ndef run():\n    return 1\n"})
    kinds = {node["qualified_name"]: node["type"] for node in graph["nodes"] if node.get("path") == "app.py"}
    assert {name for name, kind in kinds.items() if kind == "global_variable"} == {
        "app.COUNT", "app.LIMIT", "app.A", "app.B"}                     # no __all__, no os, no run
    contains = {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["type"] == "CONTAINS"}
    assert ("app.py:app", "app.py:app.COUNT") in contains


def test_reads_and_global_writes_in_the_same_module_are_edges(tmp_path):
    graph = graph_of(tmp_path, {"app.py": "COUNT = 0\nLIMIT = 3\n\ndef bump():\n    global COUNT\n    COUNT += 1\n\n"
                                          "def check(value):\n    return value < LIMIT\n"})
    assert accesses(graph) == {("app.bump", "app.COUNT"), ("app.check", "app.LIMIT")}


def test_parameters_and_local_variables_shadow_globals(tmp_path):
    graph = graph_of(tmp_path, {"app.py": "LIMIT = 3\n\ndef by_param(LIMIT):\n    return LIMIT\n\n"
                                          "def by_local():\n    LIMIT = 9\n    return LIMIT\n"})
    assert accesses(graph) == set()


def test_imported_variables_and_module_attributes_are_followed_across_modules(tmp_path):
    graph = graph_of(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/config.py": "SETTINGS = {}\nDEBUG = False\n\ndef helper():\n    return 1\n",
        "pkg/service.py": "from pkg.config import SETTINGS, helper\nimport pkg.config as config\n\n"
                          "class Service:\n    def run(self):\n        helper()\n"
                          "        return SETTINGS, config.DEBUG\n",
    })
    assert accesses(graph) == {("pkg.service.Service.run", "pkg.config.SETTINGS"),
                               ("pkg.service.Service.run", "pkg.config.DEBUG")}      # helper is a CALL, not state


def test_global_variable_nodes_get_features(tmp_path):
    graph = graph_of(tmp_path, {"app.py": "COUNT = 0\n\ndef read():\n    return COUNT\n"})
    rows = {row["node_id"]: row["features"] for row in create_node_features(graph)["nodes"]}
    assert rows["app.py:app.COUNT"]["in_degree"] == 2              # contained by app, read by read()
    assert rows["app.py:app.COUNT"]["node_type"] == 6


def test_global_edges_fit_the_hetero_data_schema(tmp_path):
    import pytest
    pytest.importorskip("torch_geometric")
    from src.ml.hetero_data import build_hetero_data
    graph = graph_of(tmp_path, {"app.py": "COUNT = 0\n\ndef read():\n    return COUNT\n\n"
                                          "class Box:\n    def get(self):\n        return COUNT\n"})
    data = build_hetero_data(graph, create_node_features(graph))
    assert data["global_variable"].x.shape[0] == 1
    assert data["module", "CONTAINS", "global_variable"].edge_index.shape[1] == 1
    assert data["function", "ACCESSES_GLOBAL", "global_variable"].edge_index.shape[1] == 1
    assert data["method", "ACCESSES_GLOBAL", "global_variable"].edge_index.shape[1] == 1


def test_calls_and_base_classes_that_resolve_to_module_variables_are_global_accesses(tmp_path):
    graph = graph_of(tmp_path, {"app.py": "import logging\nLOG = logging.getLogger()\nBase = make_base()\n\n"
                                          "class Model(Base):\n    def save(self):\n        LOG.info('x')\n"})
    assert accesses(graph) == {("app.Model", "app.Base"), ("app.Model.save", "app.LOG")}
    assert not any(edge["type"] in {"CALLS", "INHERITS"} and edge["target"].endswith((".LOG", ".Base"))
                   for edge in graph["edges"])



def test_inherits_skipped_when_class_id_is_shadowed_by_function(tmp_path):
    """DRF defines ``class X(Base)`` and ``def X`` under one name; that must not create a
    "function INHERITS" edge, which the hetero schema rejects."""
    source = ("import sys\nimport requests\n\nif sys.version_info >= (3, 9):\n    class Thing(requests.Session):\n        pass\n"
              "else:\n    def Thing():\n        return {}\n")
    graph = graph_of(tmp_path, {"compat.py": source})
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    assert all(types[edge["source"]] == "class" for edge in graph["edges"] if edge["type"] == "INHERITS")
    from src.ml.hetero_data import build_hetero_data
    build_hetero_data(graph, create_node_features(graph))   # raised ValueError before the fix
