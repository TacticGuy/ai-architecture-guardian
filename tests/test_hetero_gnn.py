from __future__ import annotations

import torch
import pytest
from torch_geometric.data import Batch

from src.ml.gnn_data import attach_touched_masks
from src.ml.hetero_data import build_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN, binary_metrics, stratified_split
from tests.test_hetero_data import make_package


def test_gnn_returns_one_logit_per_graph_and_backpropagates(tmp_path):
    result = make_package(tmp_path)
    graph = attach_touched_masks(
        build_hetero_data(result["graph"], result["features"]), ["src/pkg/core.py"]
    )
    batch = Batch.from_data_list([graph, graph])
    model = HeteroRiskGNN(
        graph.metadata(), graph["module"].x.shape[1], hidden_channels=8, layers=1, dropout=0.0
    )
    logits = model(batch)
    embeddings = model.encode(batch)
    logits.sum().backward()
    assert tuple(logits.shape) == (2,)
    assert tuple(embeddings.shape) == (2, 16)
    assert torch.allclose(logits, model.classifier(embeddings).squeeze(-1), atol=1e-6)
    assert any(parameter.grad is not None for parameter in model.parameters())


def test_stratified_split_and_metrics_are_deterministic():
    records = [{"sample_id": str(index), "label": index % 2} for index in range(20)]
    first = stratified_split(records, seed=7)
    second = stratified_split(records, seed=7)
    assert [[row["sample_id"] for row in split] for split in first] == [
        [row["sample_id"] for row in split] for split in second
    ]
    assert all({row["label"] for row in split} == {0, 1} for split in first)
    metrics = binary_metrics([0, 0, 1, 1], [0.1, 0.8, 0.7, 0.9], threshold=0.5)
    assert metrics["precision"] == 2 / 3
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 0.8
    assert 0.0 <= metrics["pr_auc_average_precision"] <= 1.0


def test_average_precision_groups_equal_scores_without_using_labels_to_break_ties():
    first = binary_metrics([1, 0, 1, 0], [0.5] * 4)
    second = binary_metrics([0, 1, 0, 1], [0.5] * 4)
    assert first["pr_auc_average_precision"] == second["pr_auc_average_precision"] == 0.5
    mixed = binary_metrics([1, 0, 1], [0.9, 0.9, 0.1])
    assert mixed["pr_auc_average_precision"] == pytest.approx(7 / 12)


def test_metrics_reject_mismatched_or_nonfinite_inputs():
    with pytest.raises(ValueError, match="same length"):
        binary_metrics([1], [])
    with pytest.raises(ValueError, match="finite probabilities"):
        binary_metrics([1], [float("nan")])
