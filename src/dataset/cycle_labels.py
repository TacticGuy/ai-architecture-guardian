"""Deterministic architectural-degradation labels from module import cycles."""
from __future__ import annotations

from typing import Any

from src.dataset.module_graph import cyclic_components, module_import_adjacency, touched_modules


def create_cycle_label(before_graph: dict[str, Any], after_graph: dict[str, Any],
                       changed_paths: list[str]) -> dict[str, Any]:
    """Label a PR risky when it creates a cyclic module component touching changed code.

    Strongly connected components provide a bounded, deterministic representation of
    dependency cycles and avoid enumerating an exponential number of simple cycles.
    """
    before_cycles = set(cyclic_components(module_import_adjacency(before_graph)))
    after_cycles = set(cyclic_components(module_import_adjacency(after_graph)))
    touched = touched_modules(after_graph, set(changed_paths))
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

