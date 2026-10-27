"""CALLS edges vs the PyCG micro-benchmark (Salis et al., ICSE 2021).

Each snippet folder holds a small program and a hand-written ``callgraph.json``
({caller: [callees]}). Both sides are reduced to internal (caller, callee) pairs:

* names: our ``qualified_name`` is already PyCG's ``module.Class.method`` form;
* instantiation: we draw ``CALLS -> Class``, PyCG lists ``Class.__init__``, so a class
  target becomes its ``__init__`` (or is dropped when the class defines none, since the
  callee is then ``object.__init__``, which PyCG does not list either);
* external targets (``<builtin>.*``, stdlib, third-party) are dropped from the gold set:
  our graph only has nodes for the project's own code.

This measures the extraction method on code that is not ours, not our dataset.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.validation_v5.metrics import counts, micro

Edge = tuple[str, str]


def discover_snippets(snippets_root: Path) -> list[tuple[str, str, Path]]:
    """(category, snippet name, folder) for every folder with a callgraph.json, sorted."""
    return sorted((path.parent.parent.name, path.parent.name, path.parent)
                  for path in Path(snippets_root).glob("*/*/callgraph.json"))


def module_names(snippet: Path) -> set[str]:
    """Dotted module names of the snippet's .py files, the way PyCG names them."""
    names = set()
    for path in snippet.rglob("*.py"):
        parts = list(path.relative_to(snippet).with_suffix("").parts)
        if parts[-1] == "__init__" and len(parts) > 1:
            parts.pop()
        names.add(".".join(parts))
    return names


def is_internal(name: str, modules: set[str]) -> bool:
    return any(name == module or name.startswith(module + ".") for module in modules)


def our_call_edges(graph: dict[str, Any]) -> set[Edge]:
    """Our CALLS edges as PyCG-style (caller, callee) names, with Class -> Class.__init__."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    names = {node_id: node["qualified_name"] for node_id, node in nodes.items()}
    edges: set[Edge] = set()
    for edge in graph["edges"]:
        if edge["type"] != "CALLS":
            continue
        target = nodes.get(edge["target"])
        if target is None or edge["source"] not in names:
            continue
        callee = target["qualified_name"]
        if target["type"] == "class":
            init = f"{callee}.__init__"
            if init not in names.values():
                continue
            callee = init
        edges.add((names[edge["source"]], callee))
    return edges


def gold_edges(callgraph: dict[str, list[str]], modules: set[str]) -> tuple[set[Edge], int]:
    """Internal gold pairs and the number of external pairs that were dropped."""
    edges, dropped = set(), 0
    for caller, callees in callgraph.items():
        for callee in callees:
            if is_internal(caller, modules) and is_internal(callee, modules):
                edges.add((caller, callee))
            else:
                dropped += 1
    return edges, dropped


def evaluate_snippet(snippet: Path, settings: dict[str, Any], predicted: set[Edge] | None = None) -> dict[str, Any]:
    """Compare one snippet. ``predicted`` defaults to our own graph's CALLS edges."""
    modules = module_names(snippet)
    gold, dropped = gold_edges(json.loads((snippet / "callgraph.json").read_text(encoding="utf-8")), modules)
    if predicted is None:
        predicted = our_call_edges(build_dependency_graph(extract_repository_ast(str(snippet), settings)))
    predicted = {edge for edge in predicted if is_internal(edge[0], modules) and is_internal(edge[1], modules)}
    return {**counts(predicted, gold), "gold_external_dropped": dropped,
            "missed": sorted(map(list, gold - predicted)), "extra": sorted(map(list, predicted - gold))}


def run_pycg(snippet: Path, python: str, timeout: int = 60) -> set[Edge] | None:
    """Run PyCG (installed in another interpreter) with main.py as entry point, as its tests do."""
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "cg.json"
        result = subprocess.run([python, "-m", "pycg", "--package", str(snippet), str(snippet / "main.py"),
                                 "-o", str(output)], capture_output=True, text=True, timeout=timeout)
        if result.returncode or not output.is_file():
            return None
        callgraph = json.loads(output.read_text(encoding="utf-8"))
    return {(caller, callee) for caller, callees in callgraph.items() for callee in callees}


def run_benchmark(snippets_root: Path, settings: dict[str, Any], pycg_python: str | None = None) -> dict[str, Any]:
    """Per-snippet rows plus micro-averaged totals per category and overall, for us and optionally PyCG."""
    tools = {"ours": None}
    if pycg_python:
        tools["pycg"] = pycg_python
    results: dict[str, Any] = {}
    for tool, python in tools.items():
        rows = []
        for category, name, snippet in discover_snippets(snippets_root):
            predicted = None
            if python:
                predicted = run_pycg(snippet, python)
                if predicted is None:
                    rows.append({"category": category, "snippet": name, "failed": True})
                    continue
            rows.append({"category": category, "snippet": name, **evaluate_snippet(snippet, settings, predicted)})
        scored = [row for row in rows if not row.get("failed")]
        categories = sorted({row["category"] for row in scored})
        results[tool] = {
            "overall": {**micro(scored), "snippets": len(scored), "failed": len(rows) - len(scored)},
            "per_category": {category: {**micro(r for r in scored if r["category"] == category),
                                        "snippets": sum(r["category"] == category for r in scored)}
                             for category in categories},
            "snippets": rows,
        }
    return results
