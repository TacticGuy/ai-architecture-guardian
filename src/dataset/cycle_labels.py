"""Deterministic architectural-degradation labels from module import cycles."""
from __future__ import annotations

from typing import Any


def create_cycle_label(before_graph: dict[str, Any], after_graph: dict[str, Any],
                       changed_paths: list[str]) -> dict[str, Any]:
    """Label a PR risky when it creates a cyclic module component touching changed code.

    Strongly connected components provide a bounded, deterministic representation of
    dependency cycles and avoid enumerating an exponential number of simple cycles.
    """
    before_cycles = set(_cyclic_components(before_graph))
    after_cycles = set(_cyclic_components(after_graph))
    touched = _touched_modules(after_graph, set(changed_paths))
    new_cycles = sorted(
        component for component in after_cycles - before_cycles
        if touched.intersection(component)
    )
    label = int(bool(new_cycles))
    return {
        "schema_version": 1,
        "label": label,
        "reason": "new_dependency_cycle" if label else "no_new_dependency_cycle",
        "new_cycles": [list(component) for component in new_cycles],
        "touched_modules": sorted(touched),
        "before_cycle_count": len(before_cycles),
        "after_cycle_count": len(after_cycles),
    }


def _module_import_graph(graph: dict[str, Any]) -> dict[str, set[str]]:
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


def _cyclic_components(graph: dict[str, Any]) -> list[tuple[str, ...]]:
    adjacency = _module_import_graph(graph)
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


def _touched_modules(graph: dict[str, Any], changed_paths: set[str]) -> set[str]:
    normalized = {path.replace("\\", "/") for path in changed_paths}
    return {
        node["qualified_name"]
        for node in graph["nodes"]
        if node["type"] == "module" and node.get("path", "").replace("\\", "/") in normalized
    }

