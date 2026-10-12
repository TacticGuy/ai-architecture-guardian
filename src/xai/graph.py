"""XAI layer C: which code files drive the structure (GNN) part of a PR's fusion score.

Method - Integrated Gradients over the node features of the PR's "before" code graph:
  * neutral graph: same nodes and edges, but every node's features set to the training
    average (0 after the checkpoint's scaler), i.e. "every module looks ordinary";
  * walk from the neutral graph to the real one in small steps and add up, for every node
    feature, how much it moved the score on the way;
  * the per-node amounts add up to score(real) - score(neutral) (checked: "completeness").
Node amounts are then summed per source file; library (external) nodes are grouped together.

The score explained is the fusion model's logit with the PR's diff vector held fixed, so a
file's number says how much that file's structure pushed this PR's risk up (+) or down (-).
The GNN is the teammate's trained checkpoint, used read-only.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import torch

from src.fusion.model import FusionModel, _mlp_logits
from src.xai.explain import ExplanationError

EXTERNAL_TYPES = {"external_module": "(external modules)", "external_callable": "(external callables)"}


def _fusion_logit(model: FusionModel, gnn_embedding: torch.Tensor, diff: torch.Tensor) -> torch.Tensor:
    features = model.features({"gnn": gnn_embedding.double(), "diff": diff.reshape(1, -1).double()})
    if model.kind == "logreg":
        return (features @ model.params["weight"] + model.params["bias"]).reshape(())
    return _mlp_logits(model.params, features).reshape(())


def _integrated_gradients(gnn, graph, fusion: FusionModel, diff: torch.Tensor, steps: int
                          ) -> tuple[dict[str, torch.Tensor], float, float]:
    """Return per-node-type attributions [nodes, features], score(real), score(neutral)."""
    real = {node_type: graph[node_type].x.detach().clone() for node_type in graph.node_types}
    work = graph.clone()                                       # never touch the caller's graph
    totals = {node_type: torch.zeros_like(value) for node_type, value in real.items()}
    with torch.enable_grad():
        for step in range(steps):
            alpha = (step + 0.5) / steps                       # midpoint rule
            inputs = {node_type: (alpha * value).requires_grad_(True) for node_type, value in real.items()}
            for node_type, value in inputs.items():
                work[node_type].x = value
            score = _fusion_logit(fusion, gnn.encode(work), diff)
            gradients = torch.autograd.grad(score, list(inputs.values()), allow_unused=True)
            for (node_type, _), gradient in zip(inputs.items(), gradients):
                if gradient is not None:
                    totals[node_type] += gradient.detach()
    attributions = {node_type: real[node_type] * totals[node_type] / steps for node_type in real}
    with torch.no_grad():
        for node_type, value in real.items():
            work[node_type].x = value
        real_score = float(_fusion_logit(fusion, gnn.encode(work), diff))
        for node_type, value in real.items():
            work[node_type].x = torch.zeros_like(value)
        neutral_score = float(_fusion_logit(fusion, gnn.encode(work), diff))
    return attributions, real_score, neutral_score


def explain_graph(*, gnn, graph, fusion: FusionModel, diff: torch.Tensor, stored_gnn: torch.Tensor,
                  feature_names: list[str], steps: int = 64, max_steps: int = 512, top_files: int = 10,
                  tolerance: float = 1e-4) -> dict[str, Any]:
    """Layer C for one PR. ``graph`` must already be scaled with the checkpoint (prepare_graph)."""
    gnn.eval()
    for parameter in gnn.parameters():
        parameter.requires_grad_(False)
    with torch.no_grad():
        embedding = gnn.encode(graph)
        gnn_probability = float(torch.sigmoid(gnn.classifier(embedding).squeeze()))
    if not torch.allclose(embedding[0].double(), stored_gnn.double(), atol=tolerance, rtol=0):
        gap = float((embedding[0].double() - stored_gnn.double()).abs().max())
        raise ExplanationError(f"the GNN checkpoint does not reproduce the saved GNN vector (max difference "
                               f"{gap:.2e}); wrong checkpoint or graph for this manifest")

    while True:                                                # more steps until the parts add up
        attributions, real_score, neutral_score = _integrated_gradients(gnn, graph, fusion, diff, steps)
        total = sum(float(value.sum()) for value in attributions.values())
        change = real_score - neutral_score
        error = abs(total - change)
        if error <= max(0.01, 0.02 * abs(change)) or steps >= max_steps:
            break
        steps *= 2

    files: dict[str, dict[str, Any]] = defaultdict(lambda: {"attribution": 0.0, "nodes": 0, "touched": False})
    by_feature = torch.zeros(len(feature_names), dtype=torch.float64)
    for node_type, values in attributions.items():
        store = graph[node_type]
        node_ids = list(store.node_ids)
        touched = store.touched_mask.tolist() if hasattr(store, "touched_mask") else [False] * len(node_ids)
        per_node = values.double().sum(dim=1).tolist()
        by_feature += values.double().sum(dim=0)
        for node_id, amount, is_touched in zip(node_ids, per_node, touched):
            key = EXTERNAL_TYPES.get(node_type) or node_id.split(":", 1)[0].replace("\\", "/")
            files[key]["attribution"] += amount
            files[key]["nodes"] += 1
            files[key]["touched"] = files[key]["touched"] or bool(is_touched)
    ranked = sorted(({"file": name, **info} for name, info in files.items()),
                    key=lambda row: (-abs(row["attribution"]), row["file"]))
    features = sorted(({"feature": name, "attribution": float(value)} for name, value in zip(feature_names, by_feature)),
                      key=lambda row: (-abs(row["attribution"]), row["feature"]))
    return {
        "explains": "fusion logit with this PR's diff held fixed: real code graph vs a neutral graph "
                    "(same nodes and edges, every node's features at the training average)",
        "gnn_probability": gnn_probability,
        "score_real": real_score, "score_neutral": neutral_score, "total_change": change,
        "completeness_error": error, "steps": steps,
        "files": ranked[:top_files], "file_count": len(ranked),
        "touched_files_total": sum(row["attribution"] for row in ranked if row["touched"]),
        "untouched_files_total": sum(row["attribution"] for row in ranked if not row["touched"]),
        "top_features": features[:5],
    }
