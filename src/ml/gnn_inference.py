"""Load a trained GNN checkpoint and score one prepared pull-request graph."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from src.ml.hetero_data import load_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN


REQUIRED_CHECKPOINT_FIELDS = {
    "model_state_dict", "metadata", "feature_names", "feature_mean",
    "feature_std", "hidden_channels", "threshold",
}


def load_gnn_checkpoint(checkpoint_path: str | Path) -> dict[str, Any]:
    """Load and validate a portable GNN checkpoint on CPU."""
    checkpoint = torch.load(Path(checkpoint_path), map_location="cpu", weights_only=False)
    missing = sorted(REQUIRED_CHECKPOINT_FIELDS - set(checkpoint))
    if missing:
        raise ValueError(f"Checkpoint is missing fields: {missing}")
    feature_count = len(checkpoint["feature_names"])
    mean = checkpoint["feature_mean"].to(device="cpu", dtype=torch.float32)
    std = checkpoint["feature_std"].to(device="cpu", dtype=torch.float32)
    if mean.numel() != feature_count or std.numel() != feature_count:
        raise ValueError("Checkpoint feature scaler does not match its feature names")
    if not torch.isfinite(mean).all() or not torch.isfinite(std).all() or bool((std <= 0).any()):
        raise ValueError("Checkpoint feature scaler contains invalid values")
    return checkpoint


def prepare_graph(graph_path: str | Path, checkpoint: dict[str, Any]):
    """Load a prepared graph and apply the checkpoint's train-only scaler."""
    graph = load_hetero_data(graph_path)
    for node_type in graph.node_types:
        if not hasattr(graph[node_type], "touched_mask"):
            raise ValueError(f"Graph has no touched_mask for node type {node_type!r}")
    feature_count = len(checkpoint["feature_names"])
    mean = checkpoint["feature_mean"].to(device="cpu", dtype=torch.float32)
    std = checkpoint["feature_std"].to(device="cpu", dtype=torch.float32)
    for node_type in graph.node_types:
        if graph[node_type].x.shape[1] != feature_count:
            raise ValueError(f"Graph feature width does not match checkpoint for {node_type!r}")
        graph[node_type].x = (torch.log1p(graph[node_type].x) - mean) / std
    return graph


def load_gnn_model(checkpoint: dict[str, Any], device: str | torch.device) -> HeteroRiskGNN:
    """Restore the trained model on the requested inference device."""
    target_device = torch.device(device)
    model = HeteroRiskGNN(
        checkpoint["metadata"],
        len(checkpoint["feature_names"]),
        int(checkpoint["hidden_channels"]),
        pooling_mode=str(checkpoint.get("pooling_mode", "repo_plus_touched")),
    ).to(target_device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model


def predict_graph(graph_path: str | Path, checkpoint_path: str | Path,
                  device: str | torch.device | None = None) -> dict[str, Any]:
    """Return a validation-threshold decision and an uncalibrated sigmoid score."""
    target_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    checkpoint = load_gnn_checkpoint(checkpoint_path)
    graph = prepare_graph(graph_path, checkpoint)
    model = load_gnn_model(checkpoint, target_device)
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
