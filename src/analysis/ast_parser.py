"""Extract syntax-level symbols, imports, calls, and static complexity from Python files."""
from __future__ import annotations

import ast
import tokenize
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


def extract_repository_ast(repository_path: str | Path, analysis_settings: dict[str, Any]) -> dict[str, Any]:
    """Parse Python sources without importing or executing any repository code."""
    root = Path(repository_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")
    excluded = set(analysis_settings["excluded_directory_names"])
    include_tests = bool(analysis_settings["include_tests"])
    max_files = int(analysis_settings["max_python_files_per_repository"])
    files = [path for path in root.rglob("*.py") if _include_file(path, root, excluded, include_tests)]
    files.sort(key=lambda path: path.relative_to(root).as_posix())
    if len(files) > max_files:
        raise ValueError(f"Repository has {len(files)} eligible Python files; configured maximum is {max_files}")
    package_dirs = find_package_directories(root, excluded)
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, str]] = []
    calls: list[dict[str, Any]] = []
    module_aliases: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    parsed_files: list[str] = []
    for source_path in files:
        relative = source_path.relative_to(root).as_posix()
        try:
            with tokenize.open(source_path) as handle:
                source = handle.read()
            tree = ast.parse(source, filename=relative, type_comments=True)
        except (OSError, SyntaxError, UnicodeError) as exc:
            errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
            continue
        parsed_files.append(relative)
        visitor = _SymbolVisitor(relative, source, module_name_for(relative, package_dirs))
        visitor.visit(tree)
        symbols.extend(visitor.symbols)
        imports.extend(visitor.imports)
        calls.extend(visitor.calls)
        if visitor.aliases:
            module_aliases[visitor.module_symbol["id"]] = dict(sorted(visitor.aliases.items()))
    return {
        "schema_version": 1,
        "repository_path": str(root),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "files": parsed_files,
        "symbols": sorted(symbols, key=lambda symbol: symbol["id"]),
        "imports": sorted(imports, key=lambda edge: (edge["source_id"], edge["target_module"])),
        "calls": sorted(calls, key=lambda edge: (edge["source_id"], edge["target_name"])),
        # For each module ID: which local names were imported, and from where.
        # Used to follow re-exports such as ``from .models import Response`` in __init__.py.
        "module_aliases": module_aliases,
        "parse_errors": errors,
    }


def _include_file(path: Path, root: Path, excluded: set[str], include_tests: bool) -> bool:
    parts = path.relative_to(root).parts
    if any(part in excluded for part in parts[:-1]):
        return False
    return include_tests or not any(part in {"tests", "test"} or part.startswith("test_") for part in parts)


def find_package_directories(root: Path, excluded: set[str]) -> set[str]:
    """Return repository-relative POSIX paths of directories that contain an ``__init__.py``.

    The repository root itself is never treated as a package.
    """
    packages: set[str] = set()
    for marker in root.rglob("__init__.py"):
        parts = marker.relative_to(root).parts[:-1]
        if parts and not any(part in excluded for part in parts):
            packages.add("/".join(parts))
    return packages


def module_name_for(relative_path: str, package_dirs: set[str]) -> str:
    """Return the dotted name Python would use to import a file.

    The name starts at the highest ancestor directory that is a package (has an
    ``__init__.py``), so ``src/pkg/core.py`` becomes ``pkg.core`` and
    ``src/pkg/__init__.py`` becomes ``pkg``. Directories without ``__init__.py``
    below that package are kept, matching Python's namespace-package rules. A file
    with no package ancestor is a top-level module named after the file.
    """
    parts = PurePosixPath(relative_path).parts
    directories, stem = parts[:-1], PurePosixPath(parts[-1]).stem
    start = len(directories)
    for depth in range(1, len(directories) + 1):
        if "/".join(directories[:depth]) in package_dirs:
            start = depth - 1
            break
    names = list(directories[start:])
    if stem != "__init__":
        names.append(stem)
    return ".".join(names) or stem


def resolve_relative_module(module_name: str, is_package: bool, level: int, module: str | None) -> str | None:
    """Turn a relative import into an absolute module name, or ``None`` if impossible.

    One dot means the package containing the current file. For an ``__init__.py`` that
    package is the module itself. Each extra dot goes one package higher.
    Example: in ``pkg.sub.mod``, ``from ..utils import x`` refers to ``pkg.utils``.
    """
    parts = module_name.split(".") if module_name else []
    package = parts if is_package else parts[:-1]
    if level - 1 >= len(package):
        return None
    base = package[:len(package) - (level - 1)]
    if module:
        base = base + module.split(".")
    return ".".join(base)


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, source: str, module_name: str) -> None:
        self.relative_path = relative_path
        self.module_name = module_name
        self.is_package = PurePosixPath(relative_path).name == "__init__.py"
        self.source_lines = source.splitlines()
        self.symbols: list[dict[str, Any]] = []
        self.imports: list[dict[str, str]] = []
        self.calls: list[dict[str, Any]] = []
        self.aliases: dict[str, str] = {}
        self.local_names: set[str] = set()
        self.scope: list[dict[str, str]] = []
        self.module_symbol = self._push_symbol("module", module_name, 1, len(self.source_lines))

    @property
    def current(self) -> dict[str, str]:
        return self.scope[-1]

    def _push_symbol(self, kind: str, name: str, line: int, end_line: int) -> dict[str, str]:
        parent = self.scope[-1]["id"] if self.scope else None
        qualified_name = name if not self.scope else f"{self.scope[-1]['qualified_name']}.{name}"
        identifier = f"{self.relative_path}:{qualified_name}"
        symbol = {"id": identifier, "type": kind, "name": name, "qualified_name": qualified_name,
                  "parent_id": parent, "path": self.relative_path, "line": line, "end_line": end_line}
        self.symbols.append(symbol)
        self.scope.append(symbol)
        return symbol

    def _pop_symbol(self) -> None:
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = self._push_symbol("class", node.name, node.lineno, getattr(node, "end_lineno", node.lineno))
        symbol.update({"base_classes": [_expression_name(base) for base in node.bases],
                       "loc": _loc(node), "docstring": bool(ast.get_docstring(node))})
        self.generic_visit(node)
        self._pop_symbol()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self.current["type"] == "class" else "function"
        symbol = self._push_symbol(kind, node.name, node.lineno, getattr(node, "end_lineno", node.lineno))
        symbol.update({"loc": _loc(node), "docstring": bool(ast.get_docstring(node)),
                       "is_async": isinstance(node, ast.AsyncFunctionDef),
                       "parameters": _parameter_features(node.args),
                       "cyclomatic_complexity": calculate_cyclomatic_complexity(node)})
        self.generic_visit(node)
        self._pop_symbol()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append({"source_id": self.current["id"], "target_module": alias.name, "from_module": None})

    def _from_base(self, node: ast.ImportFrom) -> tuple[str, str]:
        """Return the absolute module after ``from`` and the separator used to append names."""
        if node.level:
            base = resolve_relative_module(self.module_name, self.is_package, node.level, node.module)
        else:
            base = node.module
        if base is None:
            # Relative import that climbs above the top-level package: keep the
            # original dotted text so it is visibly unresolved and never linked.
            base = "." * node.level + (node.module or "")
            return base, "" if base.endswith(".") else "."
        return base, "."

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # ``from_module`` is the absolute module named after ``from``; ``target_module``
        # adds the imported name, which may itself be a submodule (``from pkg import utils``).
        base, join = self._from_base(node)
        for alias in node.names:
            target = base if alias.name == "*" else f"{base}{join}{alias.name}" if base else alias.name
            self.imports.append({"source_id": self.current["id"], "target_module": target, "from_module": base or None})

    def visit_Module(self, node: ast.Module) -> None:
        self._collect_bindings(node)
        self.generic_visit(node)

    def _collect_bindings(self, tree: ast.Module) -> None:
        """Record which local names refer to imported things and to this module's own definitions.

        ``import a.b`` binds ``a``; ``import a.b as c`` binds ``c`` to ``a.b``;
        ``from x import y as z`` binds ``z`` to ``x.y``. Imports anywhere in the file count,
        which is a deliberate simplification of Python's scoping rules.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.aliases[alias.asname] = alias.name
                    else:
                        top = alias.name.split(".", 1)[0]
                        self.aliases[top] = top
            elif isinstance(node, ast.ImportFrom):
                base, join = self._from_base(node)
                for alias in node.names:
                    if alias.name != "*":
                        self.aliases[alias.asname or alias.name] = f"{base}{join}{alias.name}" if base else alias.name
        self.local_names = {statement.name for statement in tree.body
                            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    def _enclosing_class(self) -> str | None:
        for symbol in reversed(self.scope):
            if symbol["type"] == "class":
                return symbol["qualified_name"]
        return None

    def visit_Call(self, node: ast.Call) -> None:
        raw = _expression_name(node.func)
        first, _, rest = raw.partition(".")
        qualified: str | None = None
        via_import = False
        if first in {"self", "cls"}:
            owner = self._enclosing_class()
            # Only direct attribute calls (self.method()); self.x.y() depends on runtime types.
            if owner and rest and "." not in rest:
                qualified = f"{owner}.{rest}"
        elif first in self.aliases:
            qualified = self.aliases[first] + (f".{rest}" if rest else "")
            via_import = True
        elif first in self.local_names:
            qualified = f"{self.module_name}.{raw}"
        self.calls.append({"source_id": self.current["id"], "target_name": raw,
                           "qualified_target": qualified, "via_import": via_import})
        self.generic_visit(node)


def _loc(node: ast.AST) -> int:
    return max(1, getattr(node, "end_lineno", node.lineno) - node.lineno + 1)


def _expression_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_expression_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    return type(node).__name__


def _parameter_features(arguments: ast.arguments) -> dict[str, int]:
    positional = len(arguments.posonlyargs) + len(arguments.args)
    return {"positional": positional, "keyword_only": len(arguments.kwonlyargs),
            "vararg": int(arguments.vararg is not None), "kwarg": int(arguments.kwarg is not None),
            "total": positional + len(arguments.kwonlyargs) + int(arguments.vararg is not None) + int(arguments.kwarg is not None)}


def calculate_cyclomatic_complexity(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return a deterministic McCabe-style score: one plus branch decisions."""
    score = 1
    def visit(node: ast.AST) -> None:
        nonlocal score
        for child in ast.iter_child_nodes(node):
            # Nested definitions have independent complexity and must not affect the parent.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            _count(child)
            visit(child)

    def _count(node: ast.AST) -> None:
        nonlocal score
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += max(0, len(node.values) - 1)
    visit(function)
    return score
