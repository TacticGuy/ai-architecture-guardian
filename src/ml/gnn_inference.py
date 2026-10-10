"""Load a trained GNN checkpoint and score one prepared pull-request graph."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from src.ml.hetero_data import load_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN


def predict_graph(graph_path: str | Path, checkpoint_path: str | Path,
                  device: str | torch.device | None = None) -> dict[str, Any]:
    """Return a calibrated-by-validation binary decision and raw probability."""
    target_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    checkpoint = torch.load(Path(checkpoint_path), map_location=target_device, weights_only=False)
    required = {
        "model_state_dict", "metadata", "feature_names", "feature_mean",
        "feature_std", "hidden_channels", "threshold",
    }
    missing = sorted(required - set(checkpoint))
    if missing:
        raise ValueError(f"Checkpoint is missing fields: {missing}")

    graph = load_hetero_data(graph_path)
    for node_type in graph.node_types:
        if not hasattr(graph[node_type], "touched_mask"):
            raise ValueError(f"Graph has no touched_mask for node type {node_type!r}")
    feature_count = len(checkpoint["feature_names"])
    mean = checkpoint["feature_mean"].to(dtype=torch.float32)
    std = checkpoint["feature_std"].to(dtype=torch.float32)
    if mean.numel() != feature_count or std.numel() != feature_count:
        raise ValueError("Checkpoint feature scaler does not match its feature names")
    for node_type in graph.node_types:
        if graph[node_type].x.shape[1] != feature_count:
            raise ValueError(f"Graph feature width does not match checkpoint for {node_type!r}")
        graph[node_type].x = (torch.log1p(graph[node_type].x) - mean) / std

    metadata = checkpoint["metadata"]
    model = HeteroRiskGNN(
        metadata,
        feature_count,
        int(checkpoint["hidden_channels"]),
    ).to(target_device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    with torch.no_grad():
        probability = float(torch.sigmoid(model(graph.to(target_device))).item())
    threshold = float(checkpoint["threshold"])
    return {
        "risk_probability": probability,
        "risk_percent": round(probability * 100.0, 2),
        "threshold": threshold,
        "prediction": int(probability >= threshold),
        "classification": "high_risk" if probability >= threshold else "low_risk",
        "device": str(target_device),
    }
