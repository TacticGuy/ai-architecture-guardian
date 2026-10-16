"""Fix D1: CALLS edges must follow imports, ``self``/``cls`` and same-file definitions."""
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
    write(root, "src/pkg/__init__.py", "from .models import Response\n")
    write(root, "src/pkg/utils.py", "def helper():\n    return 1\n")
    write(root, "src/pkg/other.py", "def helper():\n    return 2\n\ndef getcwd():\n    return '.'\n")
    write(root, "src/pkg/models.py", "class Response:\n    pass\n")


def calls_from(root, source_id: str) -> list[str]:
    graph = build_dependency_graph(extract_repository_ast(root, analysis_settings()))
    return sorted(edge["target"] for edge in graph["edges"] if edge["type"] == "CALLS" and edge["source"] == source_id)


def test_call_through_from_import_links_to_the_imported_function(tmp_path):
    # There are two functions called "helper"; the old short-name match gave up and made it external.
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from .utils import helper\n\ndef run():\n    return helper()\n")
    assert calls_from(tmp_path, "src/pkg/core.py:pkg.core.run") == ["src/pkg/utils.py:pkg.utils.helper"]


def test_call_through_imported_module_and_alias(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py",
          "from . import utils\nimport pkg.other as o\n\ndef run():\n    utils.helper()\n    o.helper()\n")
    assert calls_from(tmp_path, "src/pkg/core.py:pkg.core.run") == [
        "src/pkg/other.py:pkg.other.helper", "src/pkg/utils.py:pkg.utils.helper"]


def test_self_and_cls_calls_link_to_the_same_class(tmp_path):
    write(tmp_path, "engine.py",
          "class Engine:\n"
          "    def run(self):\n        return self.step()\n"
          "    def step(self):\n        return 1\n"
          "    @classmethod\n    def build(cls):\n        return cls.make()\n"
          "    @classmethod\n    def make(cls):\n        return cls()\n"
          "class Other:\n    def step(self):\n        return 2\n")
    assert calls_from(tmp_path, "engine.py:engine.Engine.run") == ["engine.py:engine.Engine.step"]
    assert calls_from(tmp_path, "engine.py:engine.Engine.build") == ["engine.py:engine.Engine.make"]


def test_call_to_function_defined_in_the_same_file(tmp_path):
    write(tmp_path, "a.py", "def helper():\n    return 1\n\ndef run():\n    return helper()\n")
    write(tmp_path, "b.py", "def helper():\n    return 2\n")
    assert calls_from(tmp_path, "a.py:a.run") == ["a.py:a.helper"]


def test_reexported_class_is_followed_to_where_it_is_defined(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from pkg import Response\n\ndef run():\n    return Response()\n")
    assert calls_from(tmp_path, "src/pkg/core.py:pkg.core.run") == ["src/pkg/models.py:pkg.models.Response"]


def test_imported_external_call_is_not_guessed_to_be_a_local_function(tmp_path):
    # The project has its own getcwd(); the old short-name match would have linked os.getcwd() to it.
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "import os\nimport numpy as np\n\ndef run():\n    os.getcwd()\n    np.array([])\n")
    assert calls_from(tmp_path, "src/pkg/core.py:pkg.core.run") == [
        "external_callable:numpy.array", "external_callable:os.getcwd"]


def test_external_call_reexported_by_a_project_module_is_named_after_its_real_source(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/compat.py", "from urllib.parse import urlparse\n")
    write(tmp_path, "src/pkg/core.py", "from .compat import urlparse\n\ndef run():\n    return urlparse('x')\n")
    assert calls_from(tmp_path, "src/pkg/core.py:pkg.core.run") == ["external_callable:urllib.parse.urlparse"]


def test_calls_record_their_resolved_full_name(tmp_path):
    make_package(tmp_path)
    write(tmp_path, "src/pkg/core.py", "from .utils import helper as h\n\ndef run():\n    h()\n")
    result = extract_repository_ast(tmp_path, analysis_settings())
    call = next(call for call in result["calls"] if call["source_id"] == "src/pkg/core.py:pkg.core.run")
    assert (call["target_name"], call["qualified_target"], call["via_import"]) == ("h", "pkg.utils.helper", True)
    assert result["module_aliases"]["src/pkg/core.py:pkg.core"] == {"h": "pkg.utils.helper"}
