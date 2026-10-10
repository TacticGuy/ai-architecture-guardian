"""Mathematically defined metrics for before/after architecture comparison."""
from __future__ import annotations

import math
from typing import Any

from src.dataset.module_graph import cyclic_components, module_import_adjacency


METRIC_NAMES: tuple[str, ...] = (
    "module_count",
    "internal_import_edge_count",
    "dependency_density",
    "mean_out_degree",
    "max_out_degree_centrality",
    "mean_clustering_coefficient",
    "structural_entropy",
    "cyclic_component_count",
    "module_loc",
    "callable_count",
    "mean_cyclomatic_complexity",
    "max_cyclomatic_complexity",
)


def calculate_structural_metrics(graph: dict[str, Any], features: dict[str, Any]) -> dict[str, int | float]:
    """Calculate bounded topology metrics and explainable size/complexity metrics.

    Dependency density is ``m / (n(n-1))`` for the simple directed graph without
    self-loops. Out-degree centrality is ``deg_out(v)/(n-1)``. Clustering uses the
    undirected projection. Structural entropy is normalized Shannon entropy of the
    incident-degree distribution and lies in ``[0, 1]``.
    """
    adjacency = module_import_adjacency(graph)
    modules = sorted(adjacency)
    n = len(modules)
    cross_edges = {(source, target) for source in modules for target in adjacency[source] if source != target}
    m = len(cross_edges)
    out_degrees = {node: sum(1 for target in adjacency[node] if target != node) for node in modules}
    density = m / (n * (n - 1)) if n > 1 else 0.0
    mean_out = m / n if n else 0.0
    max_centrality = max(out_degrees.values(), default=0) / (n - 1) if n > 1 else 0.0
    undirected = _undirected_projection(modules, cross_edges)

    feature_rows = features.get("nodes") or []
    module_loc = sum(
        int(row["features"].get("loc", 0)) for row in feature_rows if row.get("node_type") == "module"
    )
    callable_complexities = [
        int(row["features"].get("cyclomatic_complexity", 0))
        for row in feature_rows
        if row.get("node_type") in {"function", "method"}
    ]
    return {
        "module_count": n,
        "internal_import_edge_count": m,
        "dependency_density": density,
        "mean_out_degree": mean_out,
        "max_out_degree_centrality": max_centrality,
        "mean_clustering_coefficient": _mean_clustering(undirected),
        "structural_entropy": _normalized_degree_entropy(modules, cross_edges),
        "cyclic_component_count": len(cyclic_components(adjacency)),
        "module_loc": module_loc,
        "callable_count": len(callable_complexities),
        "mean_cyclomatic_complexity": (
            sum(callable_complexities) / len(callable_complexities) if callable_complexities else 0.0
        ),
        "max_cyclomatic_complexity": max(callable_complexities, default=0),
    }


def compare_structural_metrics(
    before_graph: dict[str, Any],
    before_features: dict[str, Any],
    after_graph: dict[str, Any],
    after_features: dict[str, Any],
) -> dict[str, Any]:
    """Return before, after and signed ``after - before`` values for every metric."""
    before = calculate_structural_metrics(before_graph, before_features)
    after = calculate_structural_metrics(after_graph, after_features)
    delta = {name: after[name] - before[name] for name in METRIC_NAMES}
    return {"schema_version": 1, "before": before, "after": after, "delta": delta}


def _undirected_projection(
    modules: list[str], edges: set[tuple[str, str]]
) -> dict[str, set[str]]:
    neighbors = {module: set() for module in modules}
    for source, target in edges:
        neighbors[source].add(target)
        neighbors[target].add(source)
    return neighbors


def _mean_clustering(neighbors: dict[str, set[str]]) -> float:
    if not neighbors:
        return 0.0
    coefficients: list[float] = []
    for node in sorted(neighbors):
        adjacent = sorted(neighbors[node])
        possible = len(adjacent) * (len(adjacent) - 1) / 2
        if not possible:
            coefficients.append(0.0)
            continue
        connected = sum(
            1
            for index, left in enumerate(adjacent)
            for right in adjacent[index + 1:]
            if right in neighbors[left]
        )
        coefficients.append(connected / possible)
    return sum(coefficients) / len(coefficients)


def _normalized_degree_entropy(modules: list[str], edges: set[tuple[str, str]]) -> float:
    if len(modules) <= 1 or not edges:
        return 0.0
    degrees = {module: 0 for module in modules}
    for source, target in edges:
        degrees[source] += 1
        degrees[target] += 1
    total = sum(degrees.values())
    entropy = -sum(
        (degree / total) * math.log2(degree / total)
        for degree in degrees.values()
        if degree
    )
    return entropy / math.log2(len(modules))
