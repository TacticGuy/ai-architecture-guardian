"""Fix B: relative imports (``from .x import y``) must become absolute module names."""
from __future__ import annotations

import pytest

from src.analysis.ast_parser import extract_repository_ast, resolve_relative_module
from src.analysis.dependency_graph import build_dependency_graph


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def imports_from(result: dict, path: str) -> list[tuple[str, str | None]]:
    return [(edge["target_module"], edge["from_module"]) for edge in result["imports"]
            if edge["source_id"].startswith(path + ":")]


@pytest.mark.parametrize(("module_name", "is_package", "level", "module", "expected"), [
    ("pkg.core", False, 1, "utils", "pkg.utils"),        # from .utils import ...
    ("pkg.core", False, 1, None, "pkg"),                 # from . import ...
    ("pkg", True, 1, "core", "pkg.core"),                # inside __init__.py, "." is the package itself
    ("pkg.sub.mod", False, 2, None, "pkg"),              # from .. import ...
    ("pkg.sub.mod", False, 2, "utils.text", "pkg.utils.text"),
    ("pkg.sub", True, 2, "utils", "pkg.utils"),          # from ..utils inside pkg/sub/__init__.py
    ("pkg.core", False, 2, "x", None),                   # climbs above the top-level package
    ("run", False, 1, "helpers", None),                  # file is not inside any package
])
def test_resolve_relative_module(module_name, is_package, level, module, expected):
    assert resolve_relative_module(module_name, is_package, level, module) == expected


def test_relative_imports_are_recorded_as_absolute_names(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "from .core import Engine\n")
    write(tmp_path, "src/pkg/core.py",
          "from .utils import helper\nfrom . import utils\nfrom .utils import *\n\nclass Engine:\n    pass\n")
    write(tmp_path, "src/pkg/utils.py", "def helper():\n    return 1\n")
    write(tmp_path, "src/pkg/sub/__init__.py")
    write(tmp_path, "src/pkg/sub/mod.py", "from .. import utils\nfrom ..utils import helper\n")
    result = extract_repository_ast(tmp_path, analysis_settings())
    assert imports_from(result, "src/pkg/__init__.py") == [("pkg.core.Engine", "pkg.core")]
    assert sorted(imports_from(result, "src/pkg/core.py")) == [
        ("pkg.utils", "pkg"),               # from . import utils
        ("pkg.utils", "pkg.utils"),         # from .utils import *
        ("pkg.utils.helper", "pkg.utils"),  # from .utils import helper
    ]
    assert sorted(imports_from(result, "src/pkg/sub/mod.py")) == [("pkg.utils", "pkg"), ("pkg.utils.helper", "pkg.utils")]


def test_absolute_imports_are_unchanged_and_keep_their_source_module(tmp_path):
    write(tmp_path, "sample.py", "import os\nimport a.b as c\nfrom os.path import join\n")
    result = extract_repository_ast(tmp_path, analysis_settings())
    assert sorted(imports_from(result, "sample.py")) == [
        ("a.b", None), ("os", None), ("os.path.join", "os.path")]


def test_relative_import_of_a_submodule_now_links_inside_the_project(tmp_path):
    write(tmp_path, "src/pkg/__init__.py")
    write(tmp_path, "src/pkg/core.py", "from . import utils\n")
    write(tmp_path, "src/pkg/utils.py", "VALUE = 1\n")
    graph = build_dependency_graph(extract_repository_ast(tmp_path, analysis_settings()))
    imports = [edge["target"] for edge in graph["edges"] if edge["type"] == "IMPORTS"]
    assert imports == ["src/pkg/utils.py:pkg.utils"]


def test_impossible_relative_import_stays_visibly_unresolved(tmp_path):
    write(tmp_path, "src/pkg/__init__.py")
    write(tmp_path, "src/pkg/core.py", "from ... import x\nfrom ..other import y\n")
    write(tmp_path, "src/pkg/x.py")
    result = extract_repository_ast(tmp_path, analysis_settings())
    assert sorted(imports_from(result, "src/pkg/core.py")) == [("...x", "..."), ("..other.y", "..other")]
    graph = build_dependency_graph(result)
    targets = {edge["target"] for edge in graph["edges"] if edge["type"] == "IMPORTS"}
    assert targets == {"external_module:...x", "external_module:..other.y"}  # never linked to src/pkg/x.py
