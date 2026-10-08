from __future__ import annotations

from src.analysis.ast_parser import extract_repository_ast


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 20,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def test_ast_extraction_captures_symbols_imports_calls_and_features(tmp_path):
    (tmp_path / "sample.py").write_text(
        "import os\n"
        "from package.tools import helper\n\n"
        "class Service(Base):\n"
        "    \"\"\"Service documentation.\"\"\"\n"
        "    def process(self, item, *args, option=True, **kwargs):\n"
        "        if item and option:\n"
        "            for value in args:\n"
        "                helper(value)\n"
        "        return os.getcwd()\n",
        encoding="utf-8",
    )
    result = extract_repository_ast(tmp_path, analysis_settings())
    symbols = {symbol["qualified_name"]: symbol for symbol in result["symbols"]}
    method = symbols["sample.Service.process"]
    assert symbols["sample"]["type"] == "module"
    assert symbols["sample.Service"]["base_classes"] == ["Base"]
    assert method["type"] == "method"
    assert method["parameters"] == {"positional": 2, "keyword_only": 1, "vararg": 1, "kwarg": 1, "total": 5}
    assert method["cyclomatic_complexity"] == 4
    assert {edge["target_module"] for edge in result["imports"]} == {"os", "package.tools.helper"}
    assert {edge["target_name"] for edge in result["calls"]} == {"helper", "os.getcwd"}


def test_ast_parser_skips_test_directories_and_records_syntax_errors(tmp_path):
    (tmp_path / "main.py").write_text("def okay():\n    return 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hidden.py").write_text("def hidden(): pass\n", encoding="utf-8")
    result = extract_repository_ast(tmp_path, analysis_settings())
    assert result["files"] == ["main.py"]
    assert result["parse_errors"][0]["path"] == "broken.py"
