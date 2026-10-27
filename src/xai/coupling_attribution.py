"""v5 explanations: which dependencies (edges) and code elements (nodes) drive a PR's risk score.

Three methods, all on the PR's at-merge 3-hop graph that the model actually scored:

* Edge Integrated Gradients. Every edge gets a weight ``w`` that multiplies the message it
  sends inside the GNN. Walking all weights from 0 (no message passes) to 1 (the real graph)
  and adding up the gradients gives one number per edge. Completeness: the edge numbers add
  up to ``score(real graph) - score(graph whose messages are all switched off)``.
* Node Integrated Gradients. Node features walk from the training average (0 after the
  scaler) to the real values with all edges on; per-feature numbers are summed per node.
  Completeness: they add up to ``score(real) - score(every node looks average)``.
* GNNExplainer (Ying et al., 2019) as a second, independent explainer: it learns a soft
  edge mask that keeps the prediction with as few edges as possible.

Positive numbers push the risk up, negative numbers push it down. "Score" is the model's
logit (before the sigmoid).

Unfaithfulness (Agarwal et al., 2023, as in PyTorch Geometric): keep only the top-k edges of
an explanation, re-score, and compare the two predictions with
``1 - exp(-KL(p_full || p_explained))``. 0 means the explanation alone reproduces the
prediction; values near 1 mean it does not.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from types import SimpleNamespace
from typing import Any

import torch
from torch_geometric.explain.algorithm.utils import clear_masks, set_hetero_masks

EdgeType = tuple[str, str, str]


class GraphView:
    """The minimum the GNN's ``encode`` reads from a batch, built from plain dicts, so
    explainers can feed modified node features and edge sets without copying HeteroData."""

    def __init__(self, x_dict: dict[str, torch.Tensor], edge_index_dict: dict[EdgeType, torch.Tensor],
                 touched: dict[str, torch.Tensor]) -> None:
        self._stores = {node_type: SimpleNamespace(x=x, touched_mask=touched[node_type])
                        for node_type, x in x_dict.items()}
        self.edge_index_dict = edge_index_dict
        self.num_graphs = 1

    def __getitem__(self, node_type: str) -> SimpleNamespace:
        return self._stores[node_type]


class LogitModel(torch.nn.Module):
    """``model(x_dict, edge_index_dict, touched=...)`` -> logit of shape [1] (PyG Explainer API)."""

    def __init__(self, gnn: torch.nn.Module) -> None:
        super().__init__()
        self.gnn = gnn

    def forward(self, x_dict, edge_index_dict, touched=None):  # noqa: D401
        return self.gnn(GraphView(x_dict, edge_index_dict, touched)).view(-1)


def graph_inputs(graph) -> tuple[dict[str, torch.Tensor], dict[EdgeType, torch.Tensor], dict[str, torch.Tensor]]:
    x = {node_type: graph[node_type].x for node_type in graph.node_types}
    edges = {edge_type: graph[edge_type].edge_index for edge_type in graph.edge_types
             if graph[edge_type].edge_index.numel()}
    touched = {node_type: graph[node_type].touched_mask for node_type in graph.node_types}
    return x, edges, touched


def logit_with_masks(model: LogitModel, x, edges, touched, masks: dict[EdgeType, torch.Tensor] | None) -> torch.Tensor:
    if masks is None:
        return model(x, edges, touched)[0]
    set_hetero_masks(model, masks, edges, apply_sigmoid=False)
    try:
        return model(x, edges, touched)[0]
    finally:
        clear_masks(model)


def edge_integrated_gradients(model: LogitModel, graph, steps: int = 32) -> dict[str, Any]:
    x, edges, touched = graph_inputs(graph)
    totals = {edge_type: torch.zeros(index.shape[1]) for edge_type, index in edges.items()}
    with torch.enable_grad():
        for step in range(steps):
            alpha = (step + 0.5) / steps                       # midpoint rule
            masks = {edge_type: torch.full((index.shape[1],), alpha, requires_grad=True)
                     for edge_type, index in edges.items()}
            score = logit_with_masks(model, x, edges, touched, masks)
            gradients = torch.autograd.grad(score, list(masks.values()), allow_unused=True)
            for edge_type, gradient in zip(masks, gradients):
                if gradient is not None:
                    totals[edge_type] += gradient.detach()
    attributions = {edge_type: total / steps for edge_type, total in totals.items()}   # (1 - 0) * mean gradient
    with torch.no_grad():
        real = float(logit_with_masks(model, x, edges, touched, None))
        off = float(logit_with_masks(model, x, edges, touched,
                                     {edge_type: torch.zeros(index.shape[1]) for edge_type, index in edges.items()}))
    total = float(sum(value.sum() for value in attributions.values()))
    return {"attributions": attributions, "score": real, "baseline_score": off,
            "completeness_gap": abs(total - (real - off))}


def node_integrated_gradients(model: LogitModel, graph, steps: int = 32) -> dict[str, Any]:
    x, edges, touched = graph_inputs(graph)
    totals = {node_type: torch.zeros_like(value) for node_type, value in x.items()}
    with torch.enable_grad():
        for step in range(steps):
            alpha = (step + 0.5) / steps
            inputs = {node_type: (alpha * value).requires_grad_(True) for node_type, value in x.items()}
            score = logit_with_masks(model, inputs, edges, touched, None)
            gradients = torch.autograd.grad(score, list(inputs.values()), allow_unused=True)
            for node_type, gradient in zip(inputs, gradients):
                if gradient is not None:
                    totals[node_type] += gradient.detach()
    per_feature = {node_type: x[node_type] * totals[node_type] / steps for node_type in x}
    with torch.no_grad():
        real = float(logit_with_masks(model, x, edges, touched, None))
        neutral = float(logit_with_masks(model, {k: torch.zeros_like(v) for k, v in x.items()}, edges, touched, None))
    total = float(sum(value.sum() for value in per_feature.values()))
    return {"attributions": {node_type: value.sum(dim=1) for node_type, value in per_feature.items()},
            "per_feature": per_feature, "score": real, "baseline_score": neutral,
            "completeness_gap": abs(total - (real - neutral))}


def gnnexplainer_edges(model: LogitModel, graph, epochs: int = 100, seed: int = 0) -> dict[EdgeType, torch.Tensor]:
    """Soft edge-mask importance in [0, 1] from PyG's GNNExplainer (no sign: it says which edges
    are needed for the prediction, not in which direction they push it)."""
    from torch_geometric.explain import Explainer, GNNExplainer
    torch.manual_seed(seed)
    x, edges, touched = graph_inputs(graph)
    explainer = Explainer(model=model, algorithm=GNNExplainer(epochs=epochs), explanation_type="model",
                          node_mask_type=None, edge_mask_type="object",
                          model_config={"mode": "binary_classification", "task_level": "graph",
                                        "return_type": "raw"})
    explanation = explainer(x, edges, touched=touched)
    return {edge_type: explanation[edge_type].edge_mask.detach() for edge_type in edges}


def unfaithfulness(model: LogitModel, graph, edge_scores: dict[EdgeType, torch.Tensor], top_k: int = 30,
                   use_absolute: bool = True) -> float:
    """``1 - exp(-KL(p_full || p_topk))`` keeping only the top-k edges of an explanation."""
    x, edges, touched = graph_inputs(graph)
    flat = [(float(score.abs() if use_absolute else score), edge_type, index)
            for edge_type, scores in edge_scores.items() for index, score in enumerate(scores)]
    keep = {edge_type: torch.zeros(index.shape[1]) for edge_type, index in edges.items()}
    for _, edge_type, index in sorted(flat, key=lambda item: -item[0])[:top_k]:
        keep[edge_type][index] = 1.0
    with torch.no_grad():
        full = torch.sigmoid(logit_with_masks(model, x, edges, touched, None)).item()
        explained = torch.sigmoid(logit_with_masks(model, x, edges, touched, keep)).item()
    return 1.0 - exp(-_binary_kl(full, explained))


def _binary_kl(p: float, q: float, eps: float = 1e-7) -> float:
    p, q = min(max(p, eps), 1 - eps), min(max(q, eps), 1 - eps)
    return p * log(p / q) + (1 - p) * log((1 - p) / (1 - q))


@dataclass
class GraphContext:
    """What the explanation file needs from the analysed snapshots (built from the PR's commits)."""

    node_info: dict[str, dict[str, Any]]          # at-merge analysis nodes by id
    module_of: dict[str, str | None]              # node id -> owning project module (None = external)
    before_dependency_edges: set[tuple[str, str, str]]   # (source, relation, target) before the PR
    before_node_ids: set[str]


def owner_modules(graph: dict[str, Any]) -> dict[str, str | None]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    owner: dict[str, str | None] = {}
    for node_id in nodes:
        current, seen, found = nodes.get(node_id), set(), None
        while current is not None and current["id"] not in seen:
            seen.add(current["id"])
            if current["type"] == "module":
                found = current["qualified_name"]
                break
            current = nodes.get(current.get("parent_id"))
        owner[node_id] = found
    return owner


def build_context(before_graph: dict[str, Any], after_graph: dict[str, Any]) -> GraphContext:
    dependency = {"IMPORTS", "CALLS", "INHERITS", "ACCESSES_GLOBAL"}
    return GraphContext(
        node_info={node["id"]: node for node in after_graph["nodes"]},
        module_of=owner_modules(after_graph),
        before_dependency_edges={(e["source"], e["type"], e["target"]) for e in before_graph["edges"]
                                 if e["type"] in dependency},
        before_node_ids={node["id"] for node in before_graph["nodes"]})


def ranked_edges(graph, edge_attr: dict[EdgeType, torch.Tensor], context: GraphContext, limit: int = 30,
                 gnnexplainer: dict[EdgeType, torch.Tensor] | None = None) -> list[dict[str, Any]]:
    rows = []
    touched = {node_type: graph[node_type].touched_mask for node_type in graph.node_types}
    for edge_type, scores in edge_attr.items():
        source_type, relation, target_type = edge_type
        index = graph[edge_type].edge_index
        for position, score in enumerate(scores.tolist()):
            source_i, target_i = int(index[0, position]), int(index[1, position])
            source = graph[source_type].node_ids[source_i]
            target = graph[target_type].node_ids[target_i]
            row = {"source": source, "source_type": source_type, "source_module": context.module_of.get(source),
                   "relation": relation, "target": target, "target_type": target_type,
                   "target_module": context.module_of.get(target), "attribution": round(score, 6),
                   "added_in_pr": relation != "CONTAINS" and (source, relation, target) not in context.before_dependency_edges,
                   "touched_source": bool(touched[source_type][source_i]),
                   "touched_target": bool(touched[target_type][target_i])}
            if gnnexplainer is not None:
                row["gnnexplainer_mask"] = round(float(gnnexplainer[edge_type][position]), 6)
            rows.append(row)
    rows.sort(key=lambda row: -abs(row["attribution"]))
    return rows[:limit]


def ranked_nodes(graph, node_attr: dict[str, torch.Tensor], context: GraphContext, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for node_type, scores in node_attr.items():
        for position, score in enumerate(scores.tolist()):
            node_id = graph[node_type].node_ids[position]
            info = context.node_info.get(node_id, {})
            rows.append({"id": node_id, "type": node_type, "module": context.module_of.get(node_id),
                         "file": info.get("path"), "line": info.get("line"), "end_line": info.get("end_line"),
                         "attribution": round(score, 6), "touched": bool(graph[node_type].touched_mask[position]),
                         "is_new_in_pr": node_id not in context.before_node_ids})
    rows.sort(key=lambda row: -abs(row["attribution"]))
    return rows[:limit]


def hunk_effects(diff_hunks: list[dict[str, Any]], node_rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Give each diff hunk the summed node attribution of the code elements whose lines it changes
    (new-side line numbers), so the strongest hunks point at the code that drives the score."""
    results = []
    for hunk in diff_hunks:
        start, end = hunk["lines"]
        effect = sum(row["attribution"] for row in node_rows
                     if row["file"] == hunk["file"] and row["line"] is not None and row["end_line"] is not None
                     and row["type"] not in ("module",) and row["line"] <= end and start <= row["end_line"])
        results.append({**hunk, "effect": round(effect, 6)})
    results.sort(key=lambda hunk: -abs(hunk["effect"]))
    return [hunk for hunk in results if hunk["effect"]][:limit]


def parse_hunks(diff: str, max_lines: int = 12) -> list[dict[str, Any]]:
    """Unified-diff hunks with their new-side line range and the first changed lines."""
    hunks, current, path = [], None, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            header = line.split("+", 1)[1].split(" ", 1)[0]
            start, _, length = header.partition(",")
            first, count = int(start), int(length or 1)
            current = {"file": path, "lines": [first, first + max(count, 1) - 1], "snippet": []}
            hunks.append(current)
        elif current is not None and line[:1] in "+-" and not line.startswith(("+++", "---")):
            if len(current["snippet"]) < max_lines:
                current["snippet"].append(line)
    return hunks
