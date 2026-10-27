"""Build a deterministic directed dependency graph from extracted AST facts."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_dependency_graph(ast_data: dict[str, Any]) -> dict[str, Any]:
    """Create symbol/import/call graph nodes and typed edges without executing source code."""
    symbols = [dict(symbol) for symbol in ast_data["symbols"]]
    node_by_id = {node["id"]: node for node in symbols}
    module_ids: dict[str, list[str]] = defaultdict(list)
    for node in symbols:
        if node["type"] == "module":
            module_ids[node["qualified_name"]].append(node["id"])
    # Two files can share a dotted name (e.g. scripts/run.py and tools/run.py are
    # both "run"); such names are ambiguous and must not be resolved by guessing.
    modules = {name: ids[0] for name, ids in module_ids.items() if len(ids) == 1}
    # Sets, not lists: the same ID can appear twice (e.g. @overload stubs), and that
    # must not make a name look ambiguous.
    names: dict[str, set[str]] = defaultdict(set)
    qualified: dict[str, set[str]] = defaultdict(set)
    for node in symbols:
        names[node["name"]].add(node["id"])
        names[node["qualified_name"]].add(node["id"])
        qualified[node["qualified_name"]].add(node["id"])
    module_aliases = ast_data.get("module_aliases", {})
    edges: set[tuple[str, str, str]] = set()
    for node in symbols:
        parent = node.get("parent_id")
        if parent:
            edges.add((parent, node["id"], "CONTAINS"))
    for relation in ast_data["imports"]:
        from_module = relation.get("from_module")
        target_id = _resolve_module(relation["target_module"], from_module, modules)
        if target_id is None:
            external = _external_module_name(relation["target_module"], from_module)
            target_id = f"external_module:{external}"
            node_by_id.setdefault(target_id, {"id": target_id, "type": "external_module", "name": external,
                                               "qualified_name": external, "parent_id": None})
        edges.add((relation["source_id"], target_id, "IMPORTS"))
    for relation in ast_data["calls"]:
        target_id, external = _resolve_call(relation, names, qualified, modules, module_aliases)
        if target_id is None:
            target_id = f"external_callable:{external}"
            node_by_id.setdefault(target_id, {"id": target_id, "type": "external_callable", "name": external,
                                               "qualified_name": external, "parent_id": None})
        edges.add((relation["source_id"], target_id, _dependency_kind(node_by_id, target_id, "CALLS")))
    # INHERITS: class -> parent class, resolved with exactly the same rules as calls.
    # A parent outside the project shares the "external_callable" node used when that
    # class is called elsewhere (e.g. urllib3.PoolManager), so each outside thing is one node.
    for relation in ast_data.get("inherits", []):
        # A function and a class can share one ID (e.g. ``def X`` and ``class X`` in the two
        # branches of an ``if``); the node kept for that ID may then be the function, and
        # "function INHERITS" is not a real relation, so it is skipped.
        if node_by_id.get(relation["source_id"], {}).get("type") != "class":
            continue
        target_id, external = _resolve_call(relation, names, qualified, modules, module_aliases)
        if target_id is None:
            target_id = f"external_callable:{external}"
            node_by_id.setdefault(target_id, {"id": target_id, "type": "external_callable", "name": external,
                                               "qualified_name": external, "parent_id": None})
        edges.add((relation["source_id"], target_id, _dependency_kind(node_by_id, target_id, "INHERITS")))
    # ACCESSES_GLOBAL: a function/method reads or writes a module-level variable. Only
    # targets that are real ``global_variable`` nodes become edges; anything else (an
    # imported function, a submodule) is already covered by CALLS or IMPORTS.
    for relation in ast_data.get("global_accesses", []):
        candidates = [node_id for node_id in qualified.get(relation["qualified_target"], set())
                      if node_by_id[node_id]["type"] == "global_variable"]
        if len(candidates) == 1:
            edges.add((relation["source_id"], candidates[0], "ACCESSES_GLOBAL"))
    graph_edges = [{"source": source, "target": target, "type": edge_type}
                   for source, target, edge_type in sorted(edges)]
    nodes = [node_by_id[node_id] for node_id in sorted(node_by_id)]
    return {"schema_version": 1, "repository_path": ast_data["repository_path"],
            "ast_extracted_at": ast_data["extracted_at"], "nodes": nodes, "edges": graph_edges,
            "summary": {"node_count": len(nodes), "edge_count": len(graph_edges),
                        "parsed_file_count": len(ast_data["files"]), "parse_error_count": len(ast_data["parse_errors"])}}


def _dependency_kind(node_by_id: dict[str, dict[str, Any]], target_id: str, kind: str) -> str:
    """A call or base class that resolves to a module-level variable (``LOGGER.info()``,
    ``Base = declarative_base()``) uses shared global state, so it is an ACCESSES_GLOBAL edge."""
    return "ACCESSES_GLOBAL" if node_by_id[target_id]["type"] == "global_variable" else kind


def _resolve_module(target: str, from_module: str | None, modules: dict[str, str]) -> str | None:
    """Link an import to a project module using exact names only.

    ``from X import Name`` is recorded as target ``X.Name`` with ``from_module`` ``X``.
    ``X.Name`` wins when it is itself a module (``from pkg import utils``); otherwise
    the import points at module ``X``. No suffix guessing: a third-party ``import utils``
    must not be linked to a local ``pkg.utils``.
    """
    if target in modules:
        return modules[target]
    if from_module and from_module in modules:
        return modules[from_module]
    return None


def _external_module_name(target: str, from_module: str | None) -> str:
    """Name an unresolved import after the module it comes from (``os.path``, not ``os.path.join``).

    Unresolvable relative imports (``from_module`` still starting with ``.``) keep their
    full original text so they remain recognisable.
    """
    if from_module and not from_module.startswith("."):
        return from_module
    return target


def _resolve_call(relation: dict[str, Any], names: dict[str, set[str]], qualified: dict[str, set[str]],
                  modules: dict[str, str], module_aliases: dict[str, dict[str, str]]) -> tuple[str | None, str]:
    """Return ``(node_id, external_name)``; ``node_id`` is ``None`` when the call stays external.

    1. If the parser worked out a full name (through an import, ``self``/``cls``, or a
       definition in the same file), link only by that exact name, following re-exports.
    2. A call made through an import that does not resolve is external (``os.getcwd``):
       it is never guessed to be a project function that happens to share a short name.
    3. Otherwise fall back to the old rule: a unique match on the name or short name.
    """
    target = relation["target_name"]
    full_name = relation.get("qualified_target")
    if full_name:
        found, final_name = _resolve_qualified(full_name, qualified, modules, module_aliases)
        if found:
            return found, final_name
        if relation.get("via_import"):
            return None, final_name
    short_name = target.rsplit(".", 1)[-1]
    candidates = names.get(target) or names.get(short_name) or set()
    return (next(iter(candidates)) if len(candidates) == 1 else None), target


def _resolve_qualified(name: str, qualified: dict[str, set[str]], modules: dict[str, str],
                       module_aliases: dict[str, dict[str, str]], depth: int = 0) -> tuple[str | None, str]:
    """Find the node for an exact dotted name, following re-exports through other modules.

    Returns ``(node_id or None, final_name)``. Example: ``pkg.Response`` where
    ``pkg/__init__.py`` does ``from .models import Response`` resolves to
    ``pkg.models.Response``. If the chain ends outside the project (``pkg.compat.urlparse``
    re-exporting ``urllib.parse.urlparse``), ``final_name`` is that outside name.
    """
    ids = qualified.get(name)
    if ids:
        return (next(iter(ids)) if len(ids) == 1 else None), name
    if depth >= 5:
        return None, name
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module_id = modules.get(".".join(parts[:cut]))
        if module_id is None:
            continue
        imported = module_aliases.get(module_id, {}).get(parts[cut])
        if imported is None:
            return None, name
        return _resolve_qualified(".".join([imported, *parts[cut + 1:]]), qualified, modules, module_aliases, depth + 1)
    return None, name
