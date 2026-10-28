"""IMPORTS edges vs grimp (the import graph behind import-linter) on pinned real repositories.

Both sides are reduced to the same thing: the set of internal ``module -> module`` pairs
(no self-loops) between modules of the repository's own top-level packages.

* ours: IMPORTS edges projected to modules with ``src.dataset.module_graph.module_import_adjacency``
  (the projection the labels and metrics use);
* grimp: ``build_graph(*packages)`` then ``find_modules_directly_imported_by`` for every module.

grimp runs in a separate ``python -I`` process with the source root on ``sys.path``: it only
locates the top-level packages and parses files, it never imports the cloned code.
Every disagreement can be sorted into a cause with :func:`classify_disagreements`.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.dataset.module_graph import module_import_adjacency
from src.validation_v5.metrics import counts, micro, scores

Edge = tuple[str, str]

# Pinned with `git ls-remote --tags` on 2026-10-27; the commit is recorded in results.json.
REPOSITORIES: tuple[tuple[str, str], ...] = (
    ("pallets/flask", "3.1.3"), ("pallets/click", "8.5.0"), ("psf/requests", "v2.34.2"),
    ("encode/httpx", "0.28.1"), ("Textualize/rich", "v15.0.0"), ("python-attrs/attrs", "26.1.0"),
    ("encode/starlette", "1.10.0"), ("psf/black", "26.10.1"), ("marshmallow-code/marshmallow", "4.3.1"),
    ("fastapi/typer", "0.27.3"),
)
NOT_PACKAGES = {"tests", "test", "docs", "doc", "examples", "benchmarks", "scripts", "bench", "profiling"}

CAUSES = ("TYPE_CHECKING import", "import inside a function", "relative-import resolution",
          "__init__ re-export", "conditional / try-except import", "our bug", "grimp limitation")

_GRIMP_SCRIPT = """
import json, sys
source_root, packages = sys.argv[1], sys.argv[2:]
sys.path.insert(0, source_root)
import grimp
graph = grimp.build_graph(*packages, include_external_packages=False)
edges = []
for importer in sorted(graph.modules):
    for imported in sorted(graph.find_modules_directly_imported_by(importer)):
        lines = [d["line_number"] for d in graph.get_import_details(importer=importer, imported=imported)]
        edges.append([importer, imported, lines])
print(json.dumps({"grimp_version": getattr(grimp, "__version__", None), "modules": sorted(graph.modules),
                  "edges": edges}))
"""


def normalize(module: str) -> str:
    """Import name of a module: drop a leading ``src.`` that path-based naming may add."""
    return module[4:] if module.startswith("src.") else module


def is_internal(module: str, packages: set[str]) -> bool:
    return module.split(".", 1)[0] in packages


def source_layout(repository: Path) -> tuple[Path, list[str]]:
    """The folder that goes on sys.path (``src/`` when it holds packages) and its top-level packages."""
    for root in (repository / "src", repository):
        packages = sorted(path.parent.name for path in root.glob("*/__init__.py")
                          if path.parent.name not in NOT_PACKAGES and path.parent.name.isidentifier())
        if packages:
            return root, packages
    raise ValueError(f"No top-level package found in {repository}")


def our_imports(repository: Path, settings: dict[str, Any], packages: set[str]) -> set[Edge]:
    graph = build_dependency_graph(extract_repository_ast(str(repository), settings))
    return {(normalize(source), normalize(target))
            for source, targets in module_import_adjacency(graph).items() for target in targets
            if normalize(source) != normalize(target)
            and is_internal(normalize(source), packages) and is_internal(normalize(target), packages)}


def grimp_imports(source_root: Path, packages: list[str], python: str = sys.executable,
                  timeout: int = 600) -> tuple[set[Edge], dict[Edge, list[int]], set[str], str | None]:
    """grimp's internal module pairs, the line numbers of each import, its modules and its version."""
    source_root = Path(source_root).resolve()
    result = subprocess.run([python, "-I", "-c", _GRIMP_SCRIPT, str(source_root), *packages],
                            capture_output=True, text=True, timeout=timeout, cwd=str(source_root))
    if result.returncode:
        raise RuntimeError(f"grimp failed on {source_root}: {result.stderr.strip()[-500:]}")
    payload = json.loads(result.stdout)
    lines = {(normalize(a), normalize(b)): numbers for a, b, numbers in payload["edges"] if a != b}
    return set(lines), lines, {normalize(m) for m in payload["modules"]}, payload["grimp_version"]


def module_file(source_root: Path, module: str) -> Path | None:
    base = source_root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def classify_disagreements(source_root: Path, ours: set[Edge], grimp: set[Edge],
                           grimp_lines: dict[Edge, list[int]], grimp_modules: set[str]) -> list[dict[str, Any]]:
    """Sort every disagreement into one of CAUSES by looking at the import statement itself.

    grimp-only pairs: the statement grimp saw, at its line, decides the cause (we do not count
    imports guarded by TYPE_CHECKING etc. the same way). ours-only pairs: a module grimp never
    scanned (e.g. a namespace sub-package without ``__init__.py``) is grimp's limitation; if the
    source module has an import that names the target directly, grimp missed it; if it imports
    a name from a parent package that re-exports it, we resolved through ``__init__``.
    """
    rows = []
    for edge in sorted(grimp - ours):
        context = _statement_context(source_root, edge[0], grimp_lines.get(edge, []))
        rows.append({"edge": list(edge), "only_in": "grimp", "cause": context, "lines": grimp_lines.get(edge, [])})
    for edge in sorted(ours - grimp):
        unscanned = [module for module in edge if module not in grimp_modules]
        cause = "grimp limitation" if unscanned else _ours_only_cause(source_root, *edge)
        rows.append({"edge": list(edge), "only_in": "ours", "cause": cause,
                     **({"note": f"grimp did not scan {', '.join(unscanned)}"} if unscanned else {})})
    return rows


def _statement_context(source_root: Path, module: str, lines: list[int]) -> str:
    path = module_file(source_root, module)
    if path is None or not lines:
        return "grimp limitation"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    causes = []
    for line in lines:
        chain = _ancestors_of_import(tree, line)
        if chain is None:
            causes.append("our bug")
            continue
        statement, parents = chain
        if any(isinstance(p, ast.If) and "TYPE_CHECKING" in ast.unparse(p.test) for p in parents):
            causes.append("TYPE_CHECKING import")
        elif any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) for p in parents):
            causes.append("import inside a function")
        elif any(isinstance(p, (ast.Try, ast.If)) for p in parents):
            causes.append("conditional / try-except import")
        elif isinstance(statement, ast.ImportFrom) and statement.level:
            causes.append("relative-import resolution")
        else:
            causes.append("our bug")
    # One pair can come from several statements; the pair is explained if any statement is.
    return next((cause for cause in CAUSES if cause in causes), "our bug")


def _ancestors_of_import(tree: ast.AST, line: int) -> tuple[ast.stmt, list[ast.AST]] | None:
    found = None

    def visit(node: ast.AST, parents: list[ast.AST]) -> None:
        nonlocal found
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)) and child.lineno <= line <= (child.end_lineno or line):
                found = (child, parents + [node])
            visit(child, parents + [node])

    visit(tree, [])
    return found


def _ours_only_cause(source_root: Path, module: str, target: str) -> str:
    path = module_file(source_root, module)
    if path is None:
        return "our bug"
    is_package = path.name == "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == target for alias in node.names):
                return "grimp limitation"
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(module, is_package, node.module, node.level)
            if base is None:
                continue
            if base == target or any(f"{base}.{alias.name}" == target for alias in node.names):
                return "grimp limitation"
            package = module_file(source_root, base)
            if target.startswith(base + ".") and package is not None and package.name == "__init__.py":
                return "__init__ re-export"
    return "our bug"


def _absolute(module: str, is_package: bool, name: str | None, level: int) -> str | None:
    if not level:
        return name
    parts = module.split(".")
    keep = len(parts) - level + (1 if is_package else 0)
    if keep <= 0:
        return None
    return ".".join(parts[:keep] + ([name] if name else []))


def compare_repository(repository: Path, settings: dict[str, Any], python: str = sys.executable,
                       classify: bool = False) -> dict[str, Any]:
    source_root, packages = source_layout(repository)
    ours = our_imports(repository, settings, set(packages))
    grimp, lines, modules, version = grimp_imports(source_root, packages, python)
    # Same comparison restricted to modules both tools scan, so a coverage gap is not scored as an error.
    shared = {edge for edge in ours if edge[0] in modules and edge[1] in modules}
    row: dict[str, Any] = {"packages": packages, "source_root": source_root.relative_to(repository).as_posix() or ".",
                           "grimp_version": version, **scores(**counts(ours, grimp)),
                           "shared_modules": scores(**counts(shared, grimp)),
                           "ours_edges": len(ours), "grimp_edges": len(grimp), "grimp_modules": len(modules),
                           "modules_grimp_did_not_scan": sorted({m for edge in ours for m in edge} - modules)}
    if classify:
        disagreements = classify_disagreements(source_root, ours, grimp, lines, modules)
        row["disagreements"] = disagreements
        row["causes"] = {cause: sum(d["cause"] == cause for d in disagreements) for cause in CAUSES}
    return row


def run_imports_check(repos_dir: Path, settings: dict[str, Any], classify_repos: set[str],
                      python: str = sys.executable) -> dict[str, Any]:
    rows = {}
    for name, tag in REPOSITORIES:
        folder = Path(repos_dir) / name.replace("/", "__")
        if not folder.is_dir():
            rows[name] = {"tag": tag, "missing": True}
            continue
        commit = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True,
                                text=True).stdout.strip() or None
        rows[name] = {"tag": tag, "commit": commit,
                      **compare_repository(folder, settings, python, classify=name in classify_repos)}
    scored = [row for row in rows.values() if not row.get("missing")]
    return {"per_repo": rows, "total": micro(scored)}
