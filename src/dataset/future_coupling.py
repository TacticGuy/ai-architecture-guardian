"""Automatic, forward-looking labels: does the code a PR touches keep getting more coupled?

A rule can already tell whether a PR itself creates a dependency cycle (see
``cycle_labels``), so that is not a prediction task. This module labels what a rule
cannot see at merge time: how the modules a PR touched evolve over the following months.

Definitions (module level, project modules only):

* The module dependency graph has an edge ``u -> v`` when code in module ``u`` imports,
  calls, inherits from, or accesses a module-level variable of module ``v`` (``u != v``).
* Efferent coupling ``Ce(u)`` is the out-degree of ``u``; afferent coupling ``Ca(u)`` the
  in-degree. Total coupling is ``C(u) = Ca(u) + Ce(u)``.
* The repository's mean coupling is ``C̄ = (1/n) Σ_u C(u) = 2m/n`` for ``n`` modules and ``m`` edges.
* For the touched modules ``T`` still present at both times, the coupling growth is
  ``g = (1/|T|) Σ_{u∈T} (C_future(u) − C_merge(u))`` and the repository trend is
  ``Δ = C̄_future − C̄_merge``. The excess growth is ``e = g − Δ``: how much faster the
  touched area gained links than an average module of the same project in the same period.
  Subtracting the project's own trend removes "this project was growing anyway".
* A touched module joins a new cycle when it is in a cyclic strongly connected component of
  the import graph in the future snapshot but was not at merge time.

Label 1 (degrading) when a touched module joins a new cycle or ``e > threshold``; label 0
otherwise. PRs whose touched modules no longer exist in the future snapshot get no label.
"""
from __future__ import annotations

from typing import Any

from src.dataset.module_graph import cyclic_components, module_import_adjacency

DEPENDENCY_EDGE_TYPES: tuple[str, ...] = ("IMPORTS", "CALLS", "INHERITS", "ACCESSES_GLOBAL")
SCHEMA_VERSION = 1


def module_dependency_adjacency(graph: dict[str, Any],
                                edge_types: tuple[str, ...] = DEPENDENCY_EDGE_TYPES) -> dict[str, set[str]]:
    """Project symbol-level edges onto project modules: ``u -> v`` if code in u depends on v."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    module_name = {node_id: node["qualified_name"] for node_id, node in nodes.items() if node["type"] == "module"}
    owner: dict[str, str | None] = {}

    def owning_module(node_id: str) -> str | None:
        if node_id in owner:
            return owner[node_id]
        current, seen = nodes.get(node_id), set()
        while current is not None and current["id"] not in seen:
            seen.add(current["id"])
            if current["type"] == "module":
                owner[node_id] = module_name[current["id"]]
                return owner[node_id]
            current = nodes.get(current.get("parent_id"))
        owner[node_id] = None
        return None

    adjacency = {name: set() for name in module_name.values()}
    wanted = set(edge_types)
    for edge in graph["edges"]:
        if edge["type"] not in wanted:
            continue
        source, target = owning_module(edge["source"]), owning_module(edge["target"])
        if source is not None and target is not None and source != target:
            adjacency[source].add(target)
    return adjacency


def coupling_summary(graph: dict[str, Any]) -> dict[str, Any]:
    """Small, cacheable description of a snapshot's module coupling and import cycles."""
    adjacency = module_dependency_adjacency(graph)
    afferent = {name: 0 for name in adjacency}
    for targets in adjacency.values():
        for target in targets:
            afferent[target] += 1
    paths = {node["qualified_name"]: node.get("path") for node in graph["nodes"] if node["type"] == "module"}
    cyclic = sorted({module for component in cyclic_components(module_import_adjacency(graph))
                     for module in component})
    count = len(adjacency)
    edges = sum(len(targets) for targets in adjacency.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "module_count": count,
        "edge_count": edges,
        "mean_coupling": (2 * edges / count) if count else 0.0,
        "modules": {name: {"path": paths.get(name), "ca": afferent[name], "ce": len(adjacency[name])}
                    for name in sorted(adjacency)},
        "cyclic_modules": cyclic,
    }


def touched_module_names(summary: dict[str, Any], changed_paths: list[str]) -> list[str]:
    changed = {path.replace("\\", "/") for path in changed_paths}
    return sorted(name for name, info in summary["modules"].items()
                  if (info.get("path") or "").replace("\\", "/") in changed)


def future_coupling_label(at_merge: dict[str, Any], future: dict[str, Any], touched: list[str],
                          threshold: float) -> dict[str, Any]:
    """Compare the touched modules' coupling at merge time with a later snapshot."""
    present = sorted(set(touched) & set(at_merge["modules"]) & set(future["modules"]))
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "threshold": threshold,
                              "touched_modules": sorted(touched), "compared_modules": present}
    if not present:
        result.update({"label": None, "reason": "touched_modules_missing_in_future"})
        return result

    def total(summary: dict[str, Any], name: str) -> int:
        info = summary["modules"][name]
        return int(info["ca"]) + int(info["ce"])

    growth = sum(total(future, name) - total(at_merge, name) for name in present) / len(present)
    trend = float(future["mean_coupling"]) - float(at_merge["mean_coupling"])
    excess = growth - trend
    cyclic_before, cyclic_after = set(at_merge["cyclic_modules"]), set(future["cyclic_modules"])
    joined_cycle = sorted(name for name in present if name in cyclic_after and name not in cyclic_before)
    label = int(bool(joined_cycle) or excess > threshold)
    reason = "joined_new_cycle" if joined_cycle else ("excess_coupling_growth" if label else "no_degradation")
    result.update({"label": label, "reason": reason, "coupling_growth": growth, "repository_trend": trend,
                   "excess_growth": excess, "joined_cycle": joined_cycle})
    return result


def node_delta_features(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    """For every AFTER node: (is new in this PR, dependency edges it gained, dependency edges it lost).

    Only dependency relations count (CONTAINS is structure, not coupling). The PR's code exists
    before merge, so this is legitimate model input, not information from the future.
    """
    wanted = set(DEPENDENCY_EDGE_TYPES)
    before_ids = {node["id"] for node in before["nodes"]}
    before_edges = {(e["source"], e["type"], e["target"]) for e in before["edges"] if e["type"] in wanted}
    after_edges = {(e["source"], e["type"], e["target"]) for e in after["edges"] if e["type"] in wanted}
    gained: dict[str, int] = {}
    lost: dict[str, int] = {}
    for source, _, _ in after_edges - before_edges:
        gained[source] = gained.get(source, 0) + 1
    for source, _, _ in before_edges - after_edges:
        lost[source] = lost.get(source, 0) + 1
    return {node["id"]: (int(node["id"] not in before_ids), gained.get(node["id"], 0), lost.get(node["id"], 0))
            for node in after["nodes"]}
