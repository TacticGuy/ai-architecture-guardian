"""Canonical module-import graph used by structural metrics and risk labels."""
from __future__ import annotations

from typing import Any


def module_import_adjacency(graph: dict[str, Any]) -> dict[str, set[str]]:
    """Project module adjacency where ``u -> v`` means code in u imports v."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    module_name_by_id = {
        node_id: node["qualified_name"]
        for node_id, node in nodes.items()
        if node["type"] == "module"
    }
    owner_cache: dict[str, str | None] = {}

    def owning_module(node_id: str) -> str | None:
        if node_id in owner_cache:
            return owner_cache[node_id]
        current = nodes.get(node_id)
        visited: set[str] = set()
        while current and current["id"] not in visited:
            visited.add(current["id"])
            if current["type"] == "module":
                owner_cache[node_id] = module_name_by_id[current["id"]]
                return owner_cache[node_id]
            current = nodes.get(current.get("parent_id"))
        owner_cache[node_id] = None
        return None

    adjacency = {name: set() for name in module_name_by_id.values()}
    for edge in graph["edges"]:
        if edge["type"] != "IMPORTS" or edge["target"] not in module_name_by_id:
            continue
        source = owning_module(edge["source"])
        if source is not None:
            adjacency[source].add(module_name_by_id[edge["target"]])
    return adjacency


def cyclic_components(adjacency: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Return cyclic strongly connected components using Tarjan's algorithm."""
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency[node]):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        ordered = tuple(sorted(component))
        if len(ordered) > 1 or ordered[0] in adjacency[ordered[0]]:
            components.append(ordered)

    for node in sorted(adjacency):
        if node not in indices:
            visit(node)
    return sorted(components)


def touched_modules(graph: dict[str, Any], changed_paths: set[str]) -> set[str]:
    """Map normalized changed Python paths to their project module names."""
    normalized = {path.replace("\\", "/") for path in changed_paths}
    return {
        node["qualified_name"]
        for node in graph["nodes"]
        if node["type"] == "module" and node.get("path", "").replace("\\", "/") in normalized
    }
