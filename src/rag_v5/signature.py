"""Deterministic graph-evidence signatures for design-principle retrieval."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

TAGS = frozenset({
    "new_cycle", "import_cycle_member", "mutual_import", "efferent_growth",
    "afferent_hub", "instability_rise", "cross_module_call", "added_dependency",
    "global_state", "inheritance_coupling", "god_node", "feature_envy", "low_risk",
})


def _positive(item: dict[str, Any]) -> float:
    return max(0.0, float(item.get("attribution") or 0.0))


def _instability(info: dict[str, Any], suffix: str) -> float:
    ca, ce = float(info.get(f"ca_{suffix}") or 0), float(info.get(f"ce_{suffix}") or 0)
    return ce / (ca + ce) if ca + ce else 0.0


def signature(attribution: dict[str, Any]) -> dict[str, Any]:
    """Return normalized tag weights and exact triggering evidence.

    Positive attribution is counted once per triggering edge/node *per tag*.
    Module-level facts without direct attribution receive the mean positive
    attribution (or 1 when the model supplies none). This avoids silently
    dropping a cycle merely because it is absent from the truncated top edges.
    """
    if attribution.get("schema") != "attribution_v5/1":
        raise ValueError("Expected attribution_v5/1")
    edges = attribution.get("top_edges") or []
    nodes = attribution.get("top_nodes") or []
    modules = attribution.get("module_evidence") or {}
    touched = set(attribution.get("touched_modules") or [])
    positive = [_positive(x) for x in [*edges, *nodes] if _positive(x) > 0]
    fallback = sum(positive) / len(positive) if positive else 1.0
    raw: dict[str, float] = defaultdict(float)
    triggers: dict[str, list[str]] = defaultdict(list)

    def add(tag: str, weight: float, why: str) -> None:
        if tag not in TAGS or weight <= 0:
            return
        raw[tag] += weight
        triggers[tag].append(why)

    if attribution.get("pr_creates_cycle") or attribution.get("new_cycle_modules"):
        add("new_cycle", fallback, "PR creates a cycle or names newly cyclic modules")
    for module in sorted(touched & modules.keys()):
        info = modules[module]
        if info.get("in_import_cycle"):
            add("import_cycle_member", fallback, module)
        if float(info.get("ce_after") or 0) > float(info.get("ce_before") or 0):
            add("efferent_growth", fallback, module)
        ca_after = float(info.get("ca_after") or 0)
        all_ca = sorted(float(x.get("ca_after") or 0) for x in modules.values())
        cutoff = all_ca[max(0, math.ceil(0.9 * len(all_ca)) - 1)] if all_ca else math.inf
        if ca_after >= 10 or (ca_after > 0 and ca_after >= cutoff):
            add("afferent_hub", fallback, module)
        if _instability(info, "after") > _instability(info, "before") + 1e-12:
            add("instability_rise", fallback, module)

    imports = {(e.get("source_module"), e.get("target_module")) for e in edges
               if e.get("relation") == "IMPORTS" and _positive(e) > 0}
    relations: set[str] = set()
    for edge in edges:
        weight = _positive(edge)
        if not weight:
            continue
        source, target, relation = edge.get("source_module"), edge.get("target_module"), edge.get("relation")
        label = f"{edge.get('source')} -> {relation} -> {edge.get('target')}"
        relations.add(str(relation))
        if relation == "IMPORTS" and source != target and (target, source) in imports:
            add("mutual_import", weight, label)
        if relation == "CALLS" and source and target and source != target:
            add("cross_module_call", weight, label)
        if edge.get("added_in_pr"):
            add("added_dependency", weight, label)
        if relation == "ACCESSES_GLOBAL":
            add("global_state", weight, label)
        if relation == "INHERITS" and source and target and source != target:
            add("inheritance_coupling", weight, label)

    for node in nodes:
        weight = _positive(node)
        if not weight:
            continue
        out = [e for e in edges if e.get("source") == node.get("id") and _positive(e) > 0]
        if node.get("type") in {"class", "module"} and len(out) >= 15:
            add("god_node", weight, str(node.get("id")))
        if node.get("type") == "method":
            calls = [e for e in out if e.get("relation") == "CALLS"]
            foreign = [e for e in calls if e.get("target_module") != node.get("module")]
            if calls and len(foreign) > len(calls) / 2:
                add("feature_envy", weight, str(node.get("id")))
    if float(attribution.get("risk_score") or 0) < float(attribution.get("threshold") or 0):
        add("low_risk", fallback, "risk score below decision threshold")

    total = sum(raw.values())
    weights = {tag: round(raw[tag] / total, 12) for tag in sorted(raw)} if total else {}
    text = "; ".join(f"{tag}: {', '.join(triggers[tag][:2])}" for tag in sorted(triggers))
    return {"tags": weights, "relations": sorted(relations), "triggers": dict(triggers), "evidence_text": text}
