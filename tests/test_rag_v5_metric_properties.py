"""Seeded property tests against the actual structural-metrics implementation."""
from __future__ import annotations

import random

import pytest

from src.dataset.structural_metrics import calculate_structural_metrics
from src.dataset.future_coupling import future_coupling_label


def _graph(n: int, pairs: list[tuple[int, int]]) -> dict:
    return {
        "nodes": [{"id": f"m{i}", "type": "module", "qualified_name": f"m{i}", "path": f"m{i}.py"}
                  for i in range(n)],
        "edges": [{"source": f"m{a}", "target": f"m{b}", "type": "IMPORTS"} for a, b in pairs],
    }


def test_random_graph_metric_bounds_and_degree_identity():
    rng = random.Random(2026)
    for n in range(2, 10):
        possible = [(a, b) for a in range(n) for b in range(n) if a != b]
        for _ in range(30):
            pairs = [edge for edge in possible if rng.random() < .3]
            metrics = calculate_structural_metrics(_graph(n, pairs), {"nodes": []})
            for name in ("dependency_density", "max_out_degree_centrality",
                         "mean_clustering_coefficient", "structural_entropy"):
                assert -1e-12 <= metrics[name] <= 1 + 1e-12
            m = len(pairs)
            ca = {i: 0 for i in range(n)}
            ce = {i: 0 for i in range(n)}
            for a, b in pairs:
                ce[a] += 1
                ca[b] += 1
            assert sum(ca.values()) == sum(ce.values()) == m
            assert sum(ca[i] + ce[i] for i in range(n)) / n == pytest.approx(2 * m / n)
            if m and len(set(ca[i] + ce[i] for i in range(n))) == 1:
                assert metrics["structural_entropy"] == pytest.approx(1)


def test_uniform_project_growth_and_untouched_edges():
    base = {"modules": {name: {"ca": 1, "ce": 1} for name in "abcd"},
            "mean_coupling": 2, "cyclic_modules": []}
    uniform = {"modules": {name: {"ca": 2, "ce": 1} for name in "abcd"},
               "mean_coupling": 3, "cyclic_modules": []}
    result = future_coupling_label(base, uniform, ["a"], .5)
    assert result["excess_growth"] == pytest.approx(0)
    future = {"modules": {name: dict(info) for name, info in base["modules"].items()},
              "mean_coupling": 2.5, "cyclic_modules": []}
    assert future_coupling_label(base, future, ["a"], .5)["excess_growth"] < 0
