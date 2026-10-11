from __future__ import annotations

import json

import torch
import pytest

from src.ml.gnn_data import attach_touched_masks
from src.ml.gnn_embeddings import export_gnn_embeddings, _resolve_splits
from src.ml.hetero_data import TENSOR_FEATURE_NAMES, build_hetero_data, save_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN, stratified_split
from tests.test_hetero_data import make_package


def test_exports_keyed_fixed_embeddings_and_manifest(tmp_path):
    result = make_package(tmp_path / "source")
    graph = attach_touched_masks(
        build_hetero_data(result["graph"], result["features"]), ["src/pkg/core.py"]
    )
    records = []
    data_dir = tmp_path / "samples"
    for index in range(10):
        sample_dir = data_dir / "owner__repo" / str(index)
        graph_path = sample_dir / "before" / "graph.pt"
        save_hetero_data(graph, graph_path)
        record = {
            "sample_id": f"owner/repo#{index}",
            "label": index % 2,
            "before_graph_path": "before/graph.pt",
        }
        sample_dir.mkdir(parents=True, exist_ok=True)
        (sample_dir / "metadata.json").write_text(json.dumps(record), encoding="utf-8")
        records.append(record)

    model = HeteroRiskGNN(graph.metadata(), len(TENSOR_FEATURE_NAMES), hidden_channels=8)
    train, validation, test = stratified_split(records, seed=42)
    checkpoint_path = tmp_path / "checkpoint.pt"
    torch.save({
        "model_state_dict": model.state_dict(),
        "metadata": graph.metadata(),
        "feature_names": list(TENSOR_FEATURE_NAMES),
        "feature_mean": torch.zeros(len(TENSOR_FEATURE_NAMES)),
        "feature_std": torch.ones(len(TENSOR_FEATURE_NAMES)),
        "hidden_channels": 8,
        "threshold": 0.5,
        "seed": 42,
        "split_sample_ids": {
            "train": [row["sample_id"] for row in train],
            "validation": [row["sample_id"] for row in validation],
            "test": [row["sample_id"] for row in test],
        },
    }, checkpoint_path)
    output = tmp_path / "artifacts" / "embeddings.pt"

    summary = export_gnn_embeddings(
        data_dir, checkpoint_path, output, device="cpu", batch_size=4
    )
    bundle = torch.load(output, map_location="cpu", weights_only=False)
    manifest = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

    assert summary["count"] == 10
    assert summary["embedding_dim"] == 16
    assert summary["positive"] == summary["negative"] == 5
    assert tuple(bundle["embeddings"].shape) == (10, 16)
    assert torch.isfinite(bundle["embeddings"]).all()
    assert bundle["sample_ids"] == sorted(bundle["sample_ids"])
    assert set(bundle["splits"]) == {"train", "validation", "test"}
    assert manifest["count"] == 10
    assert [row["sample_id"] for row in manifest["rows"]] == bundle["sample_ids"]


def test_old_checkpoint_cannot_invent_split_membership_from_a_seed():
    records = [{"sample_id": "owner/repo#1", "label": 1}]
    with pytest.raises(ValueError, match="membership cannot be proven"):
        _resolve_splits(records, {"seed": 42})
    split_map, source = _resolve_splits(records, {"seed": 42}, allow_smoke=True)
    assert split_map == {"owner/repo#1": "unknown"}
    assert source == "unknown_smoke_only"
