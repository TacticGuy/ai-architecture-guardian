"""Fix A: module nodes must use the dotted name Python uses to import the file."""
from __future__ import annotations

import pytest

from src.analysis.ast_parser import extract_repository_ast, find_package_directories, module_name_for
from src.analysis.dependency_graph import build_dependency_graph


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


PACKAGES = {"src/pkg", "src/pkg/sub", "src/pkg/vendored/lib", "benchmarks/benchmarks"}


@pytest.mark.parametrize(("relative_path", "expected"), [
    ("src/pkg/core.py", "pkg.core"),                         # src/ layout prefix is dropped
    ("src/pkg/__init__.py", "pkg"),                          # __init__ names the package itself
    ("src/pkg/sub/__init__.py", "pkg.sub"),                  # nested package
    ("src/pkg/sub/mod.py", "pkg.sub.mod"),                   # module in nested package
    ("src/pkg/vendored/lib/mod.py", "pkg.vendored.lib.mod"),  # folder without __init__ inside a package is kept
    ("benchmarks/benchmarks/bench_io.py", "benchmarks.bench_io"),  # only the package part counts
    ("scripts/run.py", "run"),                               # no package ancestor: plain top-level module
    ("sample.py", "sample"),                                 # root-level file is unchanged
])
def test_module_name_for(relative_path, expected):
    assert module_name_for(relative_path, PACKAGES) == expected


def test_package_directories_ignore_root_and_excluded_folders(tmp_path):
    write(tmp_path, "__init__.py")
    write(tmp_path, "src/pkg/__init__.py")
    write(tmp_path, ".venv/site/__init__.py")
    assert find_package_directories(tmp_path, {".venv"}) == {"src/pkg"}


def test_extracted_module_symbols_use_import_names(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "VERSION = 1\n")
    write(tmp_path, "src/pkg/core.py", "def run():\n    return 1\n")
    write(tmp_path, "src/pkg/sub/__init__.py")
    write(tmp_path, "src/pkg/sub/mod.py", "class Thing:\n    def go(self):\n        pass\n")
    result = extract_repository_ast(tmp_path, analysis_settings())
    modules = {symbol["path"]: symbol["qualified_name"] for symbol in result["symbols"] if symbol["type"] == "module"}
    assert modules == {"src/pkg/__init__.py": "pkg", "src/pkg/core.py": "pkg.core",
                       "src/pkg/sub/__init__.py": "pkg.sub", "src/pkg/sub/mod.py": "pkg.sub.mod"}
    qualified = {symbol["qualified_name"] for symbol in result["symbols"]}
    assert {"pkg.core.run", "pkg.sub.mod.Thing", "pkg.sub.mod.Thing.go"} <= qualified
    # Node IDs keep the file path, so they stay unique even when names are not.
    assert "src/pkg/core.py:pkg.core.run" in {symbol["id"] for symbol in result["symbols"]}


def test_absolute_import_of_package_resolves_to_its_init_module(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "VERSION = 1\n")
    write(tmp_path, "src/pkg/core.py", "import pkg\nimport pkg.helpers\n")
    write(tmp_path, "src/pkg/helpers.py", "def assist():\n    return 1\n")
    graph = build_dependency_graph(extract_repository_ast(tmp_path, analysis_settings()))
    imports = {edge["target"] for edge in graph["edges"] if edge["type"] == "IMPORTS"}
    assert imports == {"src/pkg/__init__.py:pkg", "src/pkg/helpers.py:pkg.helpers"}


def test_duplicate_module_names_are_not_guessed(tmp_path):
    write(tmp_path, "scripts/run.py", "def main():\n    pass\n")
    write(tmp_path, "tools/run.py", "def main():\n    pass\n")
    write(tmp_path, "launcher.py", "import run\n")
    graph = build_dependency_graph(extract_repository_ast(tmp_path, analysis_settings()))
    imports = [edge["target"] for edge in graph["edges"] if edge["type"] == "IMPORTS"]
    assert imports == ["external_module:run"]
