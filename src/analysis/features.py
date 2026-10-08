"""Create transparent numeric node features from AST symbols and graph topology."""
from __future__ import annotations

from collections import Counter
from typing import Any


NODE_TYPES = ("module", "class", "function", "method", "external_module", "external_callable")


def create_node_features(graph: dict[str, Any]) -> dict[str, Any]:
    """Return one explainable feature vector per graph node, with named fields and values."""
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    imports: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    contains: Counter[str] = Counter()
    for edge in graph["edges"]:
        outgoing[edge["source"]] += 1
        incoming[edge["target"]] += 1
        if edge["type"] == "IMPORTS": imports[edge["source"]] += 1
        elif edge["type"] == "CALLS": calls[edge["source"]] += 1
        elif edge["type"] == "CONTAINS": contains[edge["source"]] += 1
    records: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        parameters = node.get("parameters") or {}
        values = {
            "node_type": NODE_TYPES.index(node["type"]) if node["type"] in NODE_TYPES else -1,
            "loc": int(node.get("loc", 0)), "parameter_count": int(parameters.get("total", 0)),
            "positional_parameter_count": int(parameters.get("positional", 0)),
            "keyword_only_parameter_count": int(parameters.get("keyword_only", 0)),
            "has_vararg": int(parameters.get("vararg", 0)), "has_kwarg": int(parameters.get("kwarg", 0)),
            "cyclomatic_complexity": int(node.get("cyclomatic_complexity", 0)),
            "has_docstring": int(bool(node.get("docstring", False))), "is_async": int(bool(node.get("is_async", False))),
            "base_class_count": len(node.get("base_classes", [])), "in_degree": incoming[node["id"]],
            "out_degree": outgoing[node["id"]], "import_out_degree": imports[node["id"]],
            "call_out_degree": calls[node["id"]], "contains_out_degree": contains[node["id"]],
        }
        records.append({"node_id": node["id"], "node_type": node["type"], "feature_names": list(values),
                        "feature_values": list(values.values()), "features": values})
    return {"schema_version": 1, "repository_path": graph["repository_path"], "nodes": records,
            "summary": {"feature_node_count": len(records), "feature_dimension": len(records[0]["features"]) if records else 16,
                        "feature_names": list(records[0]["features"]) if records else _empty_feature_names()}}


def _empty_feature_names() -> list[str]:
    return ["node_type", "loc", "parameter_count", "positional_parameter_count", "keyword_only_parameter_count",
            "has_vararg", "has_kwarg", "cyclomatic_complexity", "has_docstring", "is_async", "base_class_count",
            "in_degree", "out_degree", "import_out_degree", "call_out_degree", "contains_out_degree"]
