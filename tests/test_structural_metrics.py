from __future__ import annotations

import pytest

from src.dataset.structural_metrics import calculate_structural_metrics, compare_structural_metrics


def graph(edges: list[tuple[str, str]]) -> dict:
    nodes = [
        {"id": f"{name}.py:{name}", "type": "module", "qualified_name": name, "path": f"{name}.py"}
        for name in ("a", "b", "c")
    ]
    return {
        "nodes": nodes,
        "edges": [
            {"source": f"{source}.py:{source}", "target": f"{target}.py:{target}", "type": "IMPORTS"}
            for source, target in edges
        ],
    }


def features(complexities: list[int] = [2, 4]) -> dict:
    rows = [
        {"node_type": "module", "features": {"loc": value, "cyclomatic_complexity": 0}}
        for value in (10, 20, 30)
    ]
    rows.extend(
        {"node_type": "function", "features": {"loc": 5, "cyclomatic_complexity": value}}
        for value in complexities
    )
    return {"nodes": rows}


def test_metrics_have_expected_values_for_directed_triangle():
    metrics = calculate_structural_metrics(graph([("a", "b"), ("b", "c"), ("c", "a")]), features())
    assert metrics["module_count"] == 3
    assert metrics["internal_import_edge_count"] == 3
    assert metrics["dependency_density"] == pytest.approx(0.5)
    assert metrics["mean_out_degree"] == pytest.approx(1.0)
    assert metrics["max_out_degree_centrality"] == pytest.approx(0.5)
    assert metrics["mean_clustering_coefficient"] == pytest.approx(1.0)
    assert metrics["structural_entropy"] == pytest.approx(1.0)
    assert metrics["cyclic_component_count"] == 1
    assert metrics["module_loc"] == 60
    assert metrics["callable_count"] == 2
    assert metrics["mean_cyclomatic_complexity"] == pytest.approx(3.0)
    assert metrics["max_cyclomatic_complexity"] == 4


def test_empty_topology_metrics_are_zero_and_finite():
    metrics = calculate_structural_metrics(graph([]), features([]))
    for name in (
        "dependency_density", "mean_out_degree", "max_out_degree_centrality",
        "mean_clustering_coefficient", "structural_entropy", "mean_cyclomatic_complexity",
    ):
        assert metrics[name] == 0.0
    assert metrics["cyclic_component_count"] == 0
    assert metrics["callable_count"] == 0


def test_comparison_is_signed_after_minus_before_for_every_metric():
    comparison = compare_structural_metrics(
        graph([("a", "b")]), features([2]),
        graph([("a", "b"), ("b", "c")]), features([2, 5]),
    )
    assert comparison["schema_version"] == 1
    assert comparison["delta"]["internal_import_edge_count"] == 1
    assert comparison["delta"]["callable_count"] == 1
    assert comparison["delta"]["max_cyclomatic_complexity"] == 3
    for name, before in comparison["before"].items():
        assert comparison["delta"][name] == pytest.approx(comparison["after"][name] - before)
