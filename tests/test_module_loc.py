"""Fix E: module nodes must carry their real lines-of-code value instead of 0."""
from __future__ import annotations

from src.analysis.pipeline import analyse_repository


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def analyse(tmp_path) -> dict:
    return analyse_repository(tmp_path / "repo", tmp_path / "out", analysis_settings())


def module_loc(result: dict, path: str) -> tuple[int, int]:
    """Return (loc in ast.json, loc in node_features.json) for the module stored at ``path``."""
    symbol = next(s for s in result["ast"]["symbols"] if s["type"] == "module" and s["path"] == path)
    features = next(n for n in result["features"]["nodes"] if n["node_id"] == symbol["id"])
    return symbol["loc"], features["features"]["loc"]


def test_module_loc_is_the_number_of_lines_in_the_file(tmp_path):
    write(tmp_path, "repo/sample.py",
          "# comment\nimport os\n\ndef run():\n    return os.getcwd()\n")
    assert module_loc(analyse(tmp_path), "sample.py") == (5, 5)


def test_empty_module_has_zero_loc(tmp_path):
    write(tmp_path, "repo/pkg/__init__.py", "")
    write(tmp_path, "repo/pkg/core.py", "x = 1\n")
    result = analyse(tmp_path)
    assert module_loc(result, "pkg/__init__.py") == (0, 0)
    assert module_loc(result, "pkg/core.py") == (1, 1)


def test_class_and_function_loc_are_unchanged(tmp_path):
    write(tmp_path, "repo/sample.py",
          "class A:\n    def go(self):\n        return 1\n\ndef run():\n    return 2\n")
    symbols = {s["qualified_name"]: s for s in analyse(tmp_path)["ast"]["symbols"]}
    assert (symbols["sample.A"]["loc"], symbols["sample.A.go"]["loc"], symbols["sample.run"]["loc"]) == (3, 2, 2)
