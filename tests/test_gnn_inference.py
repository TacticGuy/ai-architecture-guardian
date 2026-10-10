from __future__ import annotations

import torch

from src.ml.gnn_data import attach_touched_masks
from src.ml.gnn_inference import predict_graph
from src.ml.hetero_data import TENSOR_FEATURE_NAMES, build_hetero_data, save_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN
from tests.test_hetero_data import make_package


def test_saved_checkpoint_scores_one_prepared_graph(tmp_path):
    result = make_package(tmp_path)
    graph = attach_touched_masks(
        build_hetero_data(result["graph"], result["features"]), ["src/pkg/core.py"]
    )
    graph_path = tmp_path / "graph.pt"
    save_hetero_data(graph, graph_path)
    model = HeteroRiskGNN(
        graph.metadata(), len(TENSOR_FEATURE_NAMES), hidden_channels=8
    )
    checkpoint_path = tmp_path / "checkpoint.pt"
    torch.save({
        "model_state_dict": model.state_dict(),
        "metadata": graph.metadata(),
        "feature_names": list(TENSOR_FEATURE_NAMES),
        "feature_mean": torch.zeros(len(TENSOR_FEATURE_NAMES)),
        "feature_std": torch.ones(len(TENSOR_FEATURE_NAMES)),
        "hidden_channels": 8,
        "threshold": 0.5,
    }, checkpoint_path)

    prediction = predict_graph(graph_path, checkpoint_path, device="cpu")

    assert 0.0 <= prediction["risk_probability"] <= 1.0
    assert prediction["prediction"] in (0, 1)
    assert prediction["classification"] in ("low_risk", "high_risk")
    assert prediction["device"] == "cpu"
