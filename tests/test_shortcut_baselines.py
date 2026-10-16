from __future__ import annotations

import torch
from torch_geometric.data import HeteroData

from src.ml.shortcut_baselines import evaluate_shortcut_baselines


def _graph(nodes: int, touched: int) -> HeteroData:
    graph = HeteroData()
    graph["module"].x = torch.ones((nodes, 2))
    graph["module"].touched_mask = torch.tensor([True] * touched + [False] * (nodes - touched))
    graph[("module", "imports", "module")].edge_index = torch.empty((2, 0), dtype=torch.long)
    return graph


def _rows(split: str):
    records, graphs = [], []
    for index in range(8):
        label = index % 2
        records.append({
            "sample_id": f"org/{'a' if index < 4 else 'b'}#{split}-{index}",
            "repo": f"org/{'a' if index < 4 else 'b'}",
            "label": label,
            "merged_at": f"202{index % 4}-01-01T00:00:00Z",
            "changed_python_files": ["src/a.py"] * (label + 1),
        })
        graphs.append(_graph(3 + index, 1 + label))
    return records, graphs


def test_shortcut_baselines_report_all_controls_without_using_test_to_fit():
    train_records, train_graphs = _rows("train")
    validation_records, validation_graphs = _rows("validation")
    test_records, test_graphs = _rows("test")
    results = evaluate_shortcut_baselines(
        train_records, train_graphs, validation_records, validation_graphs,
        test_records, test_graphs,
    )
    assert set(results) == {
        "always_risky", "merge_date_only", "repository_size_only",
        "date_and_repository_size", "touched_statistics", "repository_identity",
    }
    assert results["always_risky"]["test"]["pr_auc_average_precision"] == 0.5
    assert all("precision" in result["test"] for result in results.values())
    assert results["repository_identity"]["unseen_test_repositories"] == []
