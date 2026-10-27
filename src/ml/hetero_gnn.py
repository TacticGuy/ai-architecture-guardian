"""Step 6-8: heterogeneous message passing and fixed graph embeddings."""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
import random
from typing import Any, Sequence

import torch
from torch import nn
import torch.nn.functional as F
from torch_geometric.nn import HeteroConv, SAGEConv, global_mean_pool


class HeteroRiskGNN(nn.Module):
    """Relation-aware GraphSAGE with an explicit, auditable pooling scope.

    ``repo_plus_touched`` preserves the v3 architecture.  The local modes are
    intended for v4 shortcut checks: they prevent unrelated repository nodes
    from entering the final graph embedding after message passing.
    """

    POOLING_MODES = {"repo_plus_touched", "touched_only", "touched_1hop"}

    def __init__(self, metadata: tuple[list[str], list[tuple[str, str, str]]],
                 input_channels: int, hidden_channels: int = 32, layers: int = 2,
                 dropout: float = 0.2, pooling_mode: str = "repo_plus_touched", history_dim: int = 0) -> None:
        super().__init__()
        if pooling_mode not in self.POOLING_MODES:
            raise ValueError(f"pooling_mode must be one of {sorted(self.POOLING_MODES)}")
        node_types, edge_types = metadata
        self.node_types = list(node_types)
        self.dropout = dropout
        self.pooling_mode = pooling_mode
        self.embedding_dim = hidden_channels * (2 if pooling_mode == "repo_plus_touched" else 1)
        # v5.1: optional per-PR history vector (``data.hist``, [graphs, history_dim]) joined to the
        # graph embedding before the classifier. 0 keeps the earlier architecture exactly.
        self.history_dim = history_dim
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
            nn.Linear(self.embedding_dim + history_dim, hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, 1),
        )

    def encode(self, data: Any) -> torch.Tensor:
        """Return the fixed pre-classifier graph embedding used for fusion."""
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
        selected = all_touched
        if self.pooling_mode == "touched_1hop":
            selected_by_type = _one_hop_masks(data, {
                node_type: data[node_type].touched_mask for node_type in self.node_types
            })
            selected = torch.cat([selected_by_type[node_type] for node_type in self.node_types], dim=0)

        local_embedding = _masked_mean_pool(all_embeddings, all_batches, selected, graph_count)
        if self.pooling_mode in {"touched_only", "touched_1hop"}:
            return local_embedding
        repository_embedding = global_mean_pool(all_embeddings, all_batches, size=graph_count)
        return torch.cat([repository_embedding, local_embedding], dim=1)

    def forward(self, data: Any) -> torch.Tensor:
        embedding = self.encode(data)
        if self.history_dim:
            embedding = torch.cat([embedding, data.hist.view(embedding.shape[0], self.history_dim)], dim=1)
        return self.classifier(embedding).squeeze(-1)


def _masked_mean_pool(embeddings: torch.Tensor, batches: torch.Tensor, mask: torch.Tensor,
                      graph_count: int) -> torch.Tensor:
    """Pool selected nodes, returning a zero vector for graphs with no selected node."""
    if bool(mask.any()):
        return global_mean_pool(embeddings[mask], batches[mask], size=graph_count)
    return embeddings.new_zeros((graph_count, embeddings.shape[1]))


def _one_hop_masks(data: Any, touched: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Select touched nodes and both endpoints one edge away from them.

    Expansion always uses the original touched masks, so relation iteration order
    cannot accidentally turn this into a two-or-more-hop neighbourhood.
    """
    selected = {node_type: mask.clone() for node_type, mask in touched.items()}
    for (source_type, _, target_type), edge_index in data.edge_index_dict.items():
        if edge_index.numel() == 0:
            continue
        sources, targets = edge_index[0], edge_index[1]
        from_source = touched[source_type][sources]
        from_target = touched[target_type][targets]
        if bool(from_source.any()):
            selected[target_type][targets[from_source]] = True
        if bool(from_target.any()):
            selected[source_type][sources[from_target]] = True
    return selected


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
    if len(labels) != len(probabilities):
        raise ValueError("Labels and probabilities must have the same length")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("Metrics require binary labels")
    if not isfinite(threshold) or any(not isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("Metrics require finite probabilities between zero and one")
    predictions = [int(probability >= threshold) for probability in probabilities]
    tp = sum(label == prediction == 1 for label, prediction in zip(labels, predictions))
    fp = sum(label == 0 and prediction == 1 for label, prediction in zip(labels, predictions))
    fn = sum(label == 1 and prediction == 0 for label, prediction in zip(labels, predictions))
    tn = sum(label == prediction == 0 for label, prediction in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    positives = sum(labels)
    # AP = sum(precision_at_threshold * increase_in_recall). Equal scores
    # enter at the same threshold; never break a tie using the true label.
    groups: dict[float, list[int]] = defaultdict(list)
    for probability, label in zip(probabilities, labels):
        groups[float(probability)].append(int(label))
    hits = seen = 0
    average_precision = 0.0
    for probability in sorted(groups, reverse=True):
        group = groups[probability]
        new_hits = sum(group)
        hits += new_hits
        seen += len(group)
        if positives:
            average_precision += (hits / seen) * (new_hits / positives)
    # ROC-AUC = chance that a random degrading PR scores above a random safe one (ties count half).
    negatives = len(labels) - positives
    roc_auc = 0.0
    if positives and negatives:
        below = 0
        for probability in sorted(groups):
            group = groups[probability]
            new_hits = sum(group)
            roc_auc += new_hits * (below + 0.5 * (len(group) - new_hits))
            below += len(group) - new_hits
        roc_auc /= positives * negatives
    # Review-budget view: precision among the 20% highest-scored PRs (input order breaks ties,
    # never the true label). Chance level = the share of degrading PRs.
    budget = max(1, -(-len(labels) * 20 // 100)) if labels else 0
    ranked = sorted(range(len(labels)), key=lambda index: -float(probabilities[index]))[:budget]
    return {
        "count": len(labels), "positives": positives, "threshold": threshold,
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": precision, "recall": recall, "f1": f1, "pr_auc_average_precision": average_precision,
        "accuracy": (tp + tn) / len(labels) if labels else 0.0, "roc_auc": roc_auc,
        "precision_at_top_20pct": (sum(labels[index] for index in ranked) / budget) if budget else 0.0,
        "share_degrading": positives / len(labels) if labels else 0.0, "flagged_share": (tp + fp) / len(labels) if labels else 0.0,
    }
