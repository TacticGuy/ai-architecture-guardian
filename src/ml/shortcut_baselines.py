"""Cheap controls that reveal date, repository, and size shortcut learning."""
from __future__ import annotations

from dataclasses import dataclass
from math import log1p
from typing import Any, Callable

import torch

from src.dataset.future_refactor_labels import parse_timestamp
from src.ml.hetero_gnn import binary_metrics


@dataclass
class _Rows:
    records: list[dict[str, Any]]
    graphs: list[Any]


def evaluate_shortcut_baselines(
    train_records: list[dict[str, Any]], train_graphs: list[Any],
    validation_records: list[dict[str, Any]], validation_graphs: list[Any],
    test_records: list[dict[str, Any]], test_graphs: list[Any],
) -> dict[str, Any]:
    """Fit simple train-only baselines and score validation/test without leakage."""
    groups = {
        "train": _Rows(train_records, train_graphs),
        "validation": _Rows(validation_records, validation_graphs),
        "test": _Rows(test_records, test_graphs),
    }
    repositories = sorted({_repo(record) for record in train_records})
    builders: dict[str, tuple[list[str], Callable[[dict[str, Any], Any], list[float]]]] = {
        "merge_date_only": (["merge_timestamp"], lambda record, graph: [_timestamp(record)]),
        "repository_size_only": (
            ["log_nodes", "log_edges"],
            lambda record, graph: [log1p(_node_count(graph)), log1p(_edge_count(graph))],
        ),
        "date_and_repository_size": (
            ["merge_timestamp", "log_nodes", "log_edges"],
            lambda record, graph: [
                _timestamp(record), log1p(_node_count(graph)), log1p(_edge_count(graph)),
            ],
        ),
        "touched_statistics": (
            ["log_touched_nodes", "touched_fraction", "log_changed_files"],
            lambda record, graph: [
                log1p(_touched_count(graph)),
                _touched_count(graph) / max(_node_count(graph), 1),
                log1p(len(record.get("changed_python_files", []))),
            ],
        ),
        "repository_identity": (
            [f"repo={repo}" for repo in repositories],
            lambda record, graph: [float(_repo(record) == repo) for repo in repositories],
        ),
    }
    labels = {
        name: torch.tensor([int(record["label"]) for record in rows.records], dtype=torch.float64)
        for name, rows in groups.items()
    }
    results: dict[str, Any] = {
        "always_risky": {
            "feature_names": [], "threshold": 0.5,
            "validation": binary_metrics(labels["validation"].int().tolist(),
                                           [1.0] * len(labels["validation"]), 0.5),
            "test": binary_metrics(labels["test"].int().tolist(),
                                    [1.0] * len(labels["test"]), 0.5),
        }
    }
    for name, (feature_names, builder) in builders.items():
        matrices = {
            split: torch.tensor(
                [builder(record, graph) for record, graph in zip(rows.records, rows.graphs)],
                dtype=torch.float64,
            )
            for split, rows in groups.items()
        }
        mean = matrices["train"].mean(dim=0)
        std = matrices["train"].std(dim=0, unbiased=False).clamp_min(1e-8)
        matrices = {split: (matrix - mean) / std for split, matrix in matrices.items()}
        weight, bias = _fit_logistic(matrices["train"], labels["train"])
        probabilities = {
            split: torch.sigmoid(matrix @ weight + bias).tolist()
            for split, matrix in matrices.items()
        }
        threshold = _best_f1_threshold(labels["validation"].int().tolist(), probabilities["validation"])
        results[name] = {
            "feature_names": feature_names,
            "threshold": threshold,
            "validation": binary_metrics(
                labels["validation"].int().tolist(), probabilities["validation"], threshold,
            ),
            "test": binary_metrics(labels["test"].int().tolist(), probabilities["test"], threshold),
            "unseen_test_repositories": sorted({_repo(record) for record in test_records} - set(repositories)),
        }
    return results


def _fit_logistic(features: torch.Tensor, labels: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    positives = float(labels.sum())
    negatives = float(labels.numel() - positives)
    if positives == 0 or negatives == 0:
        raise ValueError("Shortcut baselines require both labels in training")
    row_weights = torch.where(
        labels == 1, labels.numel() / (2 * positives), labels.numel() / (2 * negatives)
    )
    weight = torch.zeros(features.shape[1], dtype=torch.float64, requires_grad=True)
    bias = torch.zeros(1, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS(
        [weight, bias], max_iter=500, tolerance_grad=1e-10,
        tolerance_change=1e-12, line_search_fn="strong_wolfe",
    )

    def closure() -> torch.Tensor:
        optimizer.zero_grad()
        logits = features @ weight + bias
        loss = (row_weights * torch.nn.functional.binary_cross_entropy_with_logits(
            logits, labels, reduction="none"
        )).mean() + 0.01 * weight.square().sum()
        loss.backward()
        return loss

    optimizer.step(closure)
    return weight.detach(), bias.detach()


def _best_f1_threshold(labels: list[int], probabilities: list[float]) -> float:
    candidates = sorted(set([0.5, *probabilities]))
    return max(candidates, key=lambda value: (
        binary_metrics(labels, probabilities, value)["f1"],
        binary_metrics(labels, probabilities, value)["precision"],
        value,
    ))


def _timestamp(record: dict[str, Any]) -> float:
    value = parse_timestamp(record.get("merged_at"))
    if value is None:
        raise ValueError(f"Invalid merged_at for {record.get('sample_id')}")
    return value.timestamp()


def _repo(record: dict[str, Any]) -> str:
    repo = record.get("repo")
    if isinstance(repo, str):
        return repo
    return str(record["sample_id"]).split("#", 1)[0]


def _node_count(graph: Any) -> int:
    return sum(int(graph[node_type].x.shape[0]) for node_type in graph.node_types)


def _edge_count(graph: Any) -> int:
    return sum(int(edge_index.shape[1]) for edge_index in graph.edge_index_dict.values())


def _touched_count(graph: Any) -> int:
    return sum(int(graph[node_type].touched_mask.sum()) for node_type in graph.node_types)
