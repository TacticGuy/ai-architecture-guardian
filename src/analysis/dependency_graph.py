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
    names: dict[str, list[str]] = defaultdict(list)
    for node in symbols:
        names[node["name"]].append(node["id"])
        names[node["qualified_name"]].append(node["id"])
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
        target_id = _resolve_call(relation["target_name"], names)
        if target_id is None:
            target_id = f"external_callable:{relation['target_name']}"
            node_by_id.setdefault(target_id, {"id": target_id, "type": "external_callable", "name": relation["target_name"],
                                               "qualified_name": relation["target_name"], "parent_id": None})
        edges.add((relation["source_id"], target_id, "CALLS"))
    graph_edges = [{"source": source, "target": target, "type": edge_type}
                   for source, target, edge_type in sorted(edges)]
    nodes = [node_by_id[node_id] for node_id in sorted(node_by_id)]
    return {"schema_version": 1, "repository_path": ast_data["repository_path"],
            "ast_extracted_at": ast_data["extracted_at"], "nodes": nodes, "edges": graph_edges,
            "summary": {"node_count": len(nodes), "edge_count": len(graph_edges),
                        "parsed_file_count": len(ast_data["files"]), "parse_error_count": len(ast_data["parse_errors"])}}


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


def _resolve_call(target: str, names: dict[str, list[str]]) -> str | None:
    short_name = target.rsplit(".", 1)[-1]
    candidates = names.get(target, []) or names.get(short_name, [])
    return candidates[0] if len(candidates) == 1 else None
