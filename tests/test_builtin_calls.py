"""Fix D2: calls to Python built-ins (len, print, ...) are not part of the dependency graph."""
from __future__ import annotations

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def analyse(root) -> tuple[dict, dict]:
    result = extract_repository_ast(root, analysis_settings())
    return result, build_dependency_graph(result)


def test_builtin_calls_are_not_recorded_or_turned_into_nodes(tmp_path):
    write(tmp_path, "sample.py",
          "def run(items):\n"
          "    print(len(items))\n"
          "    if not isinstance(items, list):\n"
          "        raise ValueError('bad')\n"
          "    return sorted(dict(a=1))\n")
    result, graph = analyse(tmp_path)
    assert result["calls"] == []
    assert not any(node["type"] == "external_callable" for node in graph["nodes"])


def test_calls_inside_builtin_calls_are_still_recorded(tmp_path):
    write(tmp_path, "sample.py", "def helper():\n    return []\n\ndef run():\n    return len(helper())\n")
    result, graph = analyse(tmp_path)
    assert [call["target_name"] for call in result["calls"]] == ["helper"]
    assert ("sample.py:sample.run", "sample.py:sample.helper", "CALLS") in {
        (edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]}


def test_a_project_function_with_a_builtin_name_is_still_recorded(tmp_path):
    write(tmp_path, "files.py", "def open(path):\n    return path\n\ndef run():\n    return open('x')\n")
    write(tmp_path, "core.py", "from files import open as file_open\nfrom files import open\n\ndef go():\n    return open('y')\n")
    result, graph = analyse(tmp_path)
    targets = {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["type"] == "CALLS"}
    assert ("files.py:files.run", "files.py:files.open") in targets   # defined in the same file
    assert ("core.py:core.go", "files.py:files.open") in targets      # imported under the built-in's name


def test_method_and_module_attribute_calls_with_builtin_names_are_kept(tmp_path):
    write(tmp_path, "sample.py",
          "import logging\n\nclass Printer:\n"
          "    def print(self):\n        return 1\n"
          "    def run(self):\n        self.print()\n        logging.debug('x')\n")
    result, _ = analyse(tmp_path)
    assert sorted(call["target_name"] for call in result["calls"]) == ["logging.debug", "self.print"]
