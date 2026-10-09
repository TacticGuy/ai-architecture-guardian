"""Fix F: a class must get an INHERITS edge to each parent class it extends."""
from __future__ import annotations

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.analysis.features import create_node_features


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_package(root) -> None:
    write(root, "src/pkg/__init__.py", "from .base import Base\n")
    write(root, "src/pkg/base.py", "class Base:\n    pass\n\nclass BaseList:\n    pass\n")


def build(root) -> dict:
    return build_dependency_graph(extract_repository_ast(root, analysis_settings()))


def parents(graph: dict, class_id: str) -> list[str]:
    return sorted(edge["target"] for edge in graph["edges"]
                  if edge["type"] == "INHERITS" and edge["source"] == class_id)


def test_parent_class_in_the_same_file(tmp_path):
    write(tmp_path, "shapes.py", "class Shape:\n    pass\n\nclass Square(Shape):\n    pass\n")
    assert parents(build(tmp_path), "shapes.py:shapes.Square") == ["shapes.py:shapes.Shape"]


def test_parent_class_imported_from_another_module(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/child.py",
          "from .base import Base\nfrom . import base\n\n"
          "class Child(Base):\n    pass\n\nclass Other(base.Base):\n    pass\n")
    graph = build(tmp_path)
    assert parents(graph, "src/pkg/child.py:pkg.child.Child") == ["src/pkg/base.py:pkg.base.Base"]
    assert parents(graph, "src/pkg/child.py:pkg.child.Other") == ["src/pkg/base.py:pkg.base.Base"]


def test_parent_class_reexported_by_a_package(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/child.py", "from pkg import Base\n\nclass Child(Base):\n    pass\n")
    assert parents(build(tmp_path), "src/pkg/child.py:pkg.child.Child") == ["src/pkg/base.py:pkg.base.Base"]


def test_several_parents_and_generic_parents(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/child.py",
          "from typing import Generic, TypeVar\nfrom .base import Base, BaseList\nT = TypeVar('T')\n\n"
          "class Box(Base, BaseList[int], Generic[T]):\n    pass\n")
    assert parents(build(tmp_path), "src/pkg/child.py:pkg.child.Box") == [
        "external_callable:typing.Generic", "src/pkg/base.py:pkg.base.Base", "src/pkg/base.py:pkg.base.BaseList"]


def test_builtin_parents_are_skipped(tmp_path):
    write(tmp_path, "errors.py",
          "class AppError(Exception):\n    pass\n\nclass Plain(object):\n    pass\n\nclass Mapping(dict):\n    pass\n")
    result = extract_repository_ast(tmp_path, analysis_settings())
    assert result["inherits"] == []
    assert not any(edge["type"] == "INHERITS" for edge in build_dependency_graph(result)["edges"])
    # The existing base_class_count feature is unchanged: it still counts every listed parent.
    assert {s["name"]: len(s["base_classes"]) for s in result["symbols"] if s["type"] == "class"} == {
        "AppError": 1, "Plain": 1, "Mapping": 1}


def test_external_parent_shares_the_node_used_when_it_is_called(tmp_path):
    write(tmp_path, "client.py",
          "from urllib3 import PoolManager\n\nclass Pool(PoolManager):\n    pass\n\n"
          "def make():\n    return PoolManager()\n")
    graph = build(tmp_path)
    assert parents(graph, "client.py:client.Pool") == ["external_callable:urllib3.PoolManager"]
    calls = [edge["target"] for edge in graph["edges"] if edge["type"] == "CALLS" and edge["source"] == "client.py:client.make"]
    assert calls == ["external_callable:urllib3.PoolManager"]
    assert sum(node["id"] == "external_callable:urllib3.PoolManager" for node in graph["nodes"]) == 1


def test_subclasses_count_towards_the_parents_in_degree(tmp_path):
    write(tmp_path, "shapes.py", "class Shape:\n    pass\n\nclass Square(Shape):\n    pass\n\nclass Circle(Shape):\n    pass\n")
    features = create_node_features(build(tmp_path))
    shape = next(n for n in features["nodes"] if n["node_id"] == "shapes.py:shapes.Shape")
    # One CONTAINS edge from the module plus two INHERITS edges from the subclasses.
    assert shape["features"]["in_degree"] == 3
