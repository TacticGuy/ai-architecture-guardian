from src.validation_v5.imports_check import (
    _absolute, classify_disagreements, is_internal, normalize, our_imports, source_layout,
)

SETTINGS = {"include_tests": False, "max_python_files_per_repository": 100,
            "excluded_directory_names": ["tests"], "excluded_file_names": []}


def write(root, files):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


def test_normalize_strips_src_prefix():
    assert normalize("src.flask.app") == "flask.app"
    assert normalize("flask.app") == "flask.app"
    assert is_internal("flask.app", {"flask"}) and not is_internal("flasky.app", {"flask"})


def test_relative_import_resolution():
    assert _absolute("pkg.sub.mod", False, "other", 1) == "pkg.sub.other"
    assert _absolute("pkg.sub", True, "other", 1) == "pkg.sub.other"  # __init__ of pkg.sub
    assert _absolute("pkg.mod", False, None, 2) is None
    assert _absolute("pkg.mod", False, "abs.name", 0) == "abs.name"


def test_source_layout_prefers_src_and_skips_tests(tmp_path):
    write(tmp_path, {"src/pkg/__init__.py": "", "tests/__init__.py": "", "src/pkg/a.py": ""})
    root, packages = source_layout(tmp_path)
    assert root == tmp_path / "src" and packages == ["pkg"]


def test_our_imports_internal_module_pairs_only(tmp_path):
    write(tmp_path, {"src/pkg/__init__.py": "", "src/pkg/a.py": "import os\nfrom . import b\nfrom .b import f\n",
                     "src/pkg/b.py": "def f():\n    pass\n"})
    assert our_imports(tmp_path, SETTINGS, {"pkg"}) == {("pkg.a", "pkg.b")}


def test_every_disagreement_gets_a_cause(tmp_path):
    write(tmp_path, {
        "pkg/__init__.py": "from .impl import thing\n",
        "pkg/impl.py": "thing = 1\n",
        "pkg/a.py": ("from typing import TYPE_CHECKING\n"
                     "if TYPE_CHECKING:\n    from pkg import tc\n"
                     "def f():\n    from pkg import infunc\n"
                     "try:\n    from pkg import cond\nexcept ImportError:\n    pass\n"
                     "from pkg import thing\n"),
    })
    grimp = {("pkg.a", "pkg.tc"), ("pkg.a", "pkg.infunc"), ("pkg.a", "pkg.cond")}
    lines = {("pkg.a", "pkg.tc"): [3], ("pkg.a", "pkg.infunc"): [5], ("pkg.a", "pkg.cond"): [7]}
    ours = {("pkg.a", "pkg.impl"), ("pkg.ns.mod", "pkg.impl")}
    rows = classify_disagreements(tmp_path, ours, grimp, lines, {"pkg", "pkg.a", "pkg.impl"})
    causes = {tuple(row["edge"]): row["cause"] for row in rows}
    assert causes == {
        ("pkg.a", "pkg.tc"): "TYPE_CHECKING import",
        ("pkg.a", "pkg.infunc"): "import inside a function",
        ("pkg.a", "pkg.cond"): "conditional / try-except import",
        ("pkg.a", "pkg.impl"): "__init__ re-export",   # `from pkg import thing`, defined in pkg.impl
        ("pkg.ns.mod", "pkg.impl"): "grimp limitation",  # a module grimp never scanned
    }
