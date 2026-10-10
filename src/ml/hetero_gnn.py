"""Step 6-8: heterogeneous message passing and fixed graph embeddings."""
from __future__ import annotations

from collections import defaultdict
import random
from typing import Any, Sequence

import torch
from torch import nn
import torch.nn.functional as F
from torch_geometric.nn import HeteroConv, SAGEConv, global_mean_pool


class HeteroRiskGNN(nn.Module):
    """Relation-aware GraphSAGE with touched-area and repository pooling."""

    def __init__(self, metadata: tuple[list[str], list[tuple[str, str, str]]],
                 input_channels: int, hidden_channels: int = 32, layers: int = 2,
                 dropout: float = 0.2) -> None:
        super().__init__()
        node_types, edge_types = metadata
        self.node_types = list(node_types)
        self.dropout = dropout
        self.input_projection = nn.ModuleDict({
            node_type: nn.Linear(input_channels, hidden_channels) for node_type in node_types
        })
        self.convolutions = nn.ModuleList([
            HeteroConv({
                edge_type: SAGEConv((hidden_channels, hidden_channels), hidden_channels)
                for edge_type in edge_types
            }, aggr="sum")
            for _ in range(layers)
        ])
        self.classifier = nn.Sequential(
            nn.Linear(hidden_channels * 2, hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, 1),
        )

    def forward(self, data: Any) -> torch.Tensor:
        x = {
            node_type: F.relu(self.input_projection[node_type](data[node_type].x))
            for node_type in self.node_types
        }
        for convolution in self.convolutions:
            messages = convolution(x, data.edge_index_dict)
            x = {
                node_type: F.dropout(
                    F.relu(messages.get(node_type, current) + current),
                    p=self.dropout,
                    training=self.training,
                )
                for node_type, current in x.items()
            }

        embeddings: list[torch.Tensor] = []
        batch_indexes: list[torch.Tensor] = []
        touched: list[torch.Tensor] = []
        for node_type in self.node_types:
            embeddings.append(x[node_type])
            store = data[node_type]
            batch_indexes.append(
                store.batch if hasattr(store, "batch") else
                torch.zeros(store.x.shape[0], dtype=torch.long, device=store.x.device)
            )
            touched.append(store.touched_mask)
        all_embeddings = torch.cat(embeddings, dim=0)
        all_batches = torch.cat(batch_indexes, dim=0)
        all_touched = torch.cat(touched, dim=0)
        graph_count = int(data.num_graphs) if hasattr(data, "num_graphs") else 1
        repository_embedding = global_mean_pool(all_embeddings, all_batches, size=graph_count)
        if bool(all_touched.any()):
            touched_embedding = global_mean_pool(
                all_embeddings[all_touched], all_batches[all_touched], size=graph_count
            )
        else:
            touched_embedding = torch.zeros_like(repository_embedding)
        return self.classifier(torch.cat([repository_embedding, touched_embedding], dim=1)).squeeze(-1)


def stratified_split(records: Sequence[dict[str, Any]], seed: int = 42,
                     train_fraction: float = 0.7, validation_fraction: float = 0.15
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic smoke-test split that preserves both labels when possible."""
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[int(record["label"])].append(record)
    randomizer = random.Random(seed)
    result = [[], [], []]
    for label in sorted(groups):
        group = list(groups[label])
        randomizer.shuffle(group)
        count = len(group)
        train_end = max(1, int(count * train_fraction))
        validation_count = max(1, int(count * validation_fraction)) if count >= 3 else 0
        validation_end = min(count, train_end + validation_count)
        if count >= 3 and validation_end == count:
            validation_end -= 1
        result[0].extend(group[:train_end])
        result[1].extend(group[train_end:validation_end])
        result[2].extend(group[validation_end:])
    for split in result:
        randomizer.shuffle(split)
    return result[0], result[1], result[2]


def binary_metrics(labels: Sequence[int], probabilities: Sequence[float],
                   threshold: float = 0.5) -> dict[str, float | int]:
    predictions = [int(probability >= threshold) for probability in probabilities]
    tp = sum(label == prediction == 1 for label, prediction in zip(labels, predictions))
    fp = sum(label == 0 and prediction == 1 for label, prediction in zip(labels, predictions))
    fn = sum(label == 1 and prediction == 0 for label, prediction in zip(labels, predictions))
    tn = sum(label == prediction == 0 for label, prediction in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    positives = sum(labels)
    ranked = sorted(zip(probabilities, labels), reverse=True)
    hits = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ranked, 1):
        if label:
            hits += 1
            precision_sum += hits / rank
    average_precision = precision_sum / positives if positives else 0.0
    return {
        "count": len(labels), "positives": positives, "threshold": threshold,
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": precision, "recall": recall, "f1": f1, "pr_auc_average_precision": average_precision,
    }
