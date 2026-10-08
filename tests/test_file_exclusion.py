"""Fix D3: documentation, examples, benchmarks and build/test-config scripts are not part of the graph."""
from __future__ import annotations

import json
from pathlib import Path

from src.analysis.ast_parser import extract_repository_ast

ROOT = Path(__file__).resolve().parents[1]


def project_settings() -> dict:
    """The real static-analysis settings from config/settings.json."""
    return json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]


def write(root, relative: str, text: str = "x = 1\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repository(root) -> None:
    for relative in ["src/pkg/__init__.py", "src/pkg/core.py", "src/pkg/setup_helpers.py",
                     "src/pkg/docs_utils.py", "documentation/build_index.py",
                     "docs/conf.py", "doc/source/ext.py", "examples/demo.py", "benchmarks/bench_io.py",
                     "setup.py", "conftest.py", "src/pkg/conftest.py"]:
        write(root, relative)


def test_project_settings_skip_docs_examples_benchmarks_and_build_scripts(tmp_path):
    make_repository(tmp_path)
    files = extract_repository_ast(tmp_path, project_settings())["files"]
    assert files == ["documentation/build_index.py", "src/pkg/__init__.py", "src/pkg/core.py",
                     "src/pkg/docs_utils.py", "src/pkg/setup_helpers.py"]


def test_only_exact_file_and_folder_names_are_skipped(tmp_path):
    # Similar-looking names must stay: setup_helpers.py, docs_utils.py, documentation/.
    make_repository(tmp_path)
    files = set(extract_repository_ast(tmp_path, project_settings())["files"])
    assert {"src/pkg/setup_helpers.py", "src/pkg/docs_utils.py", "documentation/build_index.py"} <= files


def test_settings_without_excluded_file_names_still_work(tmp_path):
    make_repository(tmp_path)
    old_style = {"include_tests": False, "max_python_files_per_repository": 50,
                 "excluded_directory_names": [".git", "__pycache__"]}
    files = set(extract_repository_ast(tmp_path, old_style)["files"])
    assert {"setup.py", "conftest.py", "docs/conf.py"} <= files  # nothing extra is skipped
