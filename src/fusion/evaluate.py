"""Scoring helpers. Uses the GNN's own ``binary_metrics`` so every number is comparable."""
from __future__ import annotations

from typing import Any, Sequence

import torch

from src.ml.hetero_gnn import binary_metrics


def best_f1_threshold(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    """Same rule as scripts/train_gnn.py: the probability cut-off with the best F1 on validation."""
    candidates = sorted(set([0.5] + list(probabilities)))
    return max(candidates, key=lambda threshold: binary_metrics(labels, probabilities, threshold)["f1"])


def score(labels: Sequence[int], probabilities: Sequence[float], threshold: float,
          constant: bool = False) -> dict[str, Any]:
    """``binary_metrics`` plus a fix for constant scores (the 'always risky' baseline).

    When every score is equal there is no ranking, so PR-AUC is the share of positives
    (what a random order gives on average), not the optimistic tie-broken value.
    """
    metrics = binary_metrics(list(labels), list(probabilities), threshold)
    if constant:
        metrics["pr_auc_average_precision"] = metrics["positives"] / metrics["count"] if metrics["count"] else 0.0
    return metrics


def bootstrap(labels: Sequence[int], probabilities: Sequence[float], threshold: float, rounds: int,
              seed: int, constant: bool = False) -> dict[str, Any]:
    """Re-score on ``rounds`` random resamples (with replacement) of the rows; report the middle 95%.

    With 15 test PRs one mistake moves F1 a lot; this range shows how much.
    """
    if rounds <= 0:
        return {"rounds": 0}
    generator = torch.Generator().manual_seed(seed)
    count = len(labels)
    f1_values: list[float] = []
    ap_values: list[float] = []
    for _ in range(rounds):
        rows = torch.randint(count, (count,), generator=generator).tolist()
        sample_labels = [labels[row] for row in rows]
        if sum(sample_labels) == 0:  # PR-AUC is undefined without a positive
            continue
        metrics = score(sample_labels, [probabilities[row] for row in rows], threshold, constant)
        f1_values.append(metrics["f1"])
        ap_values.append(metrics["pr_auc_average_precision"])
    if not f1_values:
        return {"rounds": rounds, "used": 0}
    return {"rounds": rounds, "used": len(f1_values),
            "f1_95_range": _middle_95(f1_values), "pr_auc_95_range": _middle_95(ap_values)}


def _middle_95(values: list[float]) -> list[float]:
    tensor = torch.tensor(values, dtype=torch.float64)
    return [float(torch.quantile(tensor, 0.025)), float(torch.quantile(tensor, 0.975))]
