"""Fix C: ``from X import Name`` must create an IMPORTS edge to module X."""
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


def make_package(root) -> None:
    write(root, "src/pkg/__init__.py", "VERSION = 1\n")
    write(root, "src/pkg/utils.py", "def helper():\n    return 1\n\ndef other():\n    return 2\n")
    write(root, "src/pkg/models.py", "class Response:\n    pass\n")


def import_targets(root, source_path: str) -> list[str]:
    graph = build_dependency_graph(extract_repository_ast(root, analysis_settings()))
    return sorted(edge["target"] for edge in graph["edges"]
                  if edge["type"] == "IMPORTS" and edge["source"].startswith(source_path + ":"))


def test_from_import_of_a_function_links_to_its_module(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from pkg.utils import helper\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["src/pkg/utils.py:pkg.utils"]


def test_relative_from_import_of_a_class_links_to_its_module(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from .models import Response\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["src/pkg/models.py:pkg.models"]


def test_from_package_import_submodule_links_to_the_submodule(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from pkg import utils\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["src/pkg/utils.py:pkg.utils"]


def test_from_package_import_name_links_to_the_package(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from pkg import VERSION\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["src/pkg/__init__.py:pkg"]


def test_several_names_from_one_module_give_one_edge(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from .utils import helper, other\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["src/pkg/utils.py:pkg.utils"]


def test_external_modules_are_named_after_the_module_imported_from(tmp_path):
    write(tmp_path, "sample.py", "import os\nfrom os.path import join, exists\nfrom collections import abc\n")
    assert import_targets(tmp_path, "sample.py") == [
        "external_module:collections", "external_module:os", "external_module:os.path"]


def test_third_party_module_is_not_guessed_to_be_a_local_one(tmp_path):
    # The old suffix match linked "import utils" to the project's own pkg.utils.
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "import utils\nfrom models import Response\n")
    assert import_targets(tmp_path, "src/pkg/core.py") == ["external_module:models", "external_module:utils"]
