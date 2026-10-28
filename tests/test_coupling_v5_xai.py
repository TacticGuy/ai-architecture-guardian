"""v5 explanations (edge/node Integrated Gradients, GNNExplainer, unfaithfulness) and packed graphs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from src.dataset.pr_history import merged_prs_from_history  # noqa: E402
from src.ml.coupling_data import (  # noqa: E402
    INPUT_FEATURE_NAMES, discover_coupling_samples, fit_scaler, apply_scaler, load_coupling_graph,
    load_packed_graphs, pack_graphs,
)
from src.ml.hetero_gnn import HeteroRiskGNN  # noqa: E402
from src.xai.coupling_attribution import (  # noqa: E402
    LogitModel, edge_integrated_gradients, gnnexplainer_edges, hunk_effects, node_integrated_gradients,
    parse_hunks, unfaithfulness,
)
from tests.test_future_coupling import SETTINGS, history_repo  # noqa: E402,F401  (fixture)


@pytest.fixture
def sample(history_repo, tmp_path):  # noqa: F811
    from src.dataset.coupling_builder import Snapshotter, build_coupling_sample
    import subprocess
    clones = tmp_path / "clones"
    clones.mkdir()
    # A real local clone (not a symlink, which Windows only allows with developer mode).
    subprocess.run(["git", "clone", "-q", str(history_repo), str(clones / "o__r")], check=True)
    prs = {pr.number: pr for pr in merged_prs_from_history(history_repo)}
    out = tmp_path / "samples"
    build_coupling_sample("o/r", prs[1], Snapshotter(history_repo, tmp_path / "wt"), out, tmp_path / "cache",
                          SETTINGS, horizon_months=6, threshold=0.5)
    record = discover_coupling_samples(out)[0]
    return {"record": record, "clones": clones, "root": tmp_path}


def model_for(graph, seed: int = 3) -> LogitModel:
    torch.manual_seed(seed)
    gnn = HeteroRiskGNN(graph.metadata(), len(INPUT_FEATURE_NAMES), 16, layers=2, pooling_mode="touched_1hop")
    gnn.eval()
    for parameter in gnn.parameters():
        parameter.requires_grad_(False)
    return LogitModel(gnn).eval()


def scaled_graph(record):
    graph = load_coupling_graph(record)
    mean, std = fit_scaler([graph])
    return apply_scaler(graph, mean, std), mean, std


def test_packed_graphs_round_trip_without_node_ids(sample, tmp_path):
    path = tmp_path / "graphs.pt"
    assert pack_graphs([sample["record"]], path) == 1
    [packed] = load_packed_graphs(path)
    original = load_coupling_graph(sample["record"])
    assert packed.sample_id == original.sample_id and float(packed.y) == float(original.y)
    for node_type in original.node_types:
        assert torch.equal(packed[node_type].x, original[node_type].x)
        assert not hasattr(packed[node_type], "node_ids")


def test_integrated_gradients_add_up_to_the_score_change(sample):
    graph, _, _ = scaled_graph(sample["record"])
    model = model_for(graph)
    edges = edge_integrated_gradients(model, graph, steps=64)
    nodes = node_integrated_gradients(model, graph, steps=64)
    for result in (edges, nodes):
        change = result["score"] - result["baseline_score"]
        assert result["completeness_gap"] <= 0.02 * abs(change) + 1e-3   # float32 sums, 64 midpoint steps
    assert edges["score"] == pytest.approx(nodes["score"])
    assert set(edges["attributions"]) <= set(graph.edge_types)


def test_unfaithfulness_is_zero_when_every_edge_is_kept_and_bounded_otherwise(sample):
    graph, _, _ = scaled_graph(sample["record"])
    model = model_for(graph)
    scores = edge_integrated_gradients(model, graph, steps=8)["attributions"]
    total = sum(int(value.numel()) for value in scores.values())
    assert unfaithfulness(model, graph, scores, top_k=total) == pytest.approx(0.0, abs=1e-6)
    value = unfaithfulness(model, graph, scores, top_k=1)
    assert 0.0 <= value <= 1.0


def test_gnnexplainer_gives_one_mask_value_per_edge(sample):
    graph, _, _ = scaled_graph(sample["record"])
    model = model_for(graph)
    masks = gnnexplainer_edges(model, graph, epochs=5)
    for edge_type, mask in masks.items():
        assert mask.shape[0] == graph[edge_type].edge_index.shape[1]
        assert float(mask.min()) >= 0.0 and float(mask.max()) <= 1.0


def test_hunks_get_the_attribution_of_the_code_they_change():
    diff = ("diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1,2 +1,4 @@\n+import pkg.b\n+\n"
            " def f():\n-    return 1\n+    return pkg.b.X\n")
    [hunk] = parse_hunks(diff)
    assert hunk["file"] == "pkg/a.py" and hunk["lines"] == [1, 4] and hunk["snippet"][0] == "+import pkg.b"
    nodes = [{"file": "pkg/a.py", "type": "function", "line": 3, "end_line": 4, "attribution": 0.3},
             {"file": "pkg/a.py", "type": "module", "line": 1, "end_line": 4, "attribution": 5.0},
             {"file": "pkg/b.py", "type": "function", "line": 1, "end_line": 9, "attribution": 9.0}]
    [result] = hunk_effects([hunk], nodes)
    assert result["effect"] == pytest.approx(0.3)


def test_explain_script_writes_the_contract_file(sample, tmp_path):
    from scripts.explain_coupling_v5 import SCHEMA, explain_sample, file_name
    record = sample["record"]
    graph, mean, std = scaled_graph(record)
    model = model_for(graph)
    checkpoint = tmp_path / "model.pt"
    torch.save({"model_state_dict": model.gnn.state_dict(), "metadata": graph.metadata(),
                "feature_names": list(INPUT_FEATURE_NAMES), "feature_mean": mean, "feature_std": std,
                "hidden_channels": 16, "layers": 2, "pooling_mode": "touched_1hop", "threshold": 0.5, "seed": 3},
               checkpoint)
    out = tmp_path / "xai"
    result = explain_sample(record, "test", str(checkpoint), str(sample["clones"]), str(out), SETTINGS, 16, 5)
    assert result["status"] == "written"
    payload = json.loads((out / file_name(record["sample_id"])).read_text())
    assert payload["schema"] == SCHEMA and payload["sample_id"] == "o/r#1" and payload["split"] == "test"
    layer = payload["layer_a"]
    assert layer["base"] + layer["structure_gnn"] + layer["history"] + layer["diff"] == pytest.approx(
        payload["logit"], abs=1e-5)
    assert 0 < len(payload["top_edges"]) <= 30
    assert [abs(e["attribution"]) for e in payload["top_edges"]] == sorted(
        (abs(e["attribution"]) for e in payload["top_edges"]), reverse=True)
    added = [e for e in payload["top_edges"] if e["added_in_pr"]]
    assert all(e["relation"] != "CONTAINS" for e in added)
    assert payload["module_evidence"]["pkg.a"]["ce_after"] == payload["module_evidence"]["pkg.a"]["ce_before"] + 1
    assert 0.0 <= payload["unfaithfulness"] <= 1.0
    assert explain_sample(record, "test", str(checkpoint), str(sample["clones"]), str(out), SETTINGS, 16, 5)[
        "status"] == "existing"


def test_pack_for_kaggle_writes_every_upload_file(sample, tmp_path):
    import gzip
    import zipfile
    from scripts.pack_v5_for_kaggle import main as pack_main
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"train": [], "validation": [], "test": ["o/r"]}), encoding="utf-8")
    out = tmp_path / "kaggle"
    data_dir = Path(sample["record"]["_dir"]).parents[1]
    assert pack_main(["--data-dir", str(data_dir), "--out-dir", str(out), "--split", str(split)]) == 0
    assert {p.name for p in out.iterdir()} == {"graphs_v5.pt.gz", "diffs_v5.jsonl", "coupling_split_v5.json",
                                               "code.zip", "v5_manifest.jsonl"}
    with gzip.open(out / "graphs_v5.pt.gz", "rb") as source, open(tmp_path / "g.pt", "wb") as target:
        target.write(source.read())
    assert [g.sample_id for g in load_packed_graphs(tmp_path / "g.pt")] == ["o/r#1"]
    names = zipfile.ZipFile(out / "code.zip").namelist()
    assert "scripts/train_coupling_gnn.py" in names and "src/ml/coupling_data.py" in names
    assert not any("__pycache__" in name for name in names)


def test_history_features_feed_the_model_and_the_explanation(sample, tmp_path):
    from scripts.explain_coupling_v5 import explain_sample, file_name
    from src.dataset.history_features import HISTORY_FEATURE_NAMES
    from src.ml.coupling_data import apply_history_scaler, fit_history_scaler
    from src.xai.coupling_attribution import structure_history_split
    record = sample["record"]
    values = {name: float(index + 1) for index, name in enumerate(HISTORY_FEATURE_NAMES)}
    (Path(record["_dir"]) / "history.json").write_text(json.dumps({"features": values}), encoding="utf-8")
    graph, mean, std = scaled_graph(record)
    assert graph.hist.shape == (1, len(HISTORY_FEATURE_NAMES))
    history_mean, history_std = fit_history_scaler([graph])
    torch.manual_seed(5)
    gnn = HeteroRiskGNN(graph.metadata(), len(INPUT_FEATURE_NAMES), 16, layers=2, pooling_mode="touched_1hop",
                        history_dim=len(HISTORY_FEATURE_NAMES)).eval()
    for parameter in gnn.parameters():
        parameter.requires_grad_(False)
    model = LogitModel(gnn, apply_history_scaler(graph.clone(), history_mean, history_std).hist).eval()
    parts = structure_history_split(model, graph)
    assert parts["base"] + parts["structure_gnn"] + parts["history"] == pytest.approx(parts["logit"], abs=1e-5)
    checkpoint = tmp_path / "model_history.pt"
    torch.save({"model_state_dict": gnn.state_dict(), "metadata": graph.metadata(),
                "feature_names": list(INPUT_FEATURE_NAMES), "feature_mean": mean, "feature_std": std,
                "hidden_channels": 16, "layers": 2, "pooling_mode": "touched_1hop", "threshold": 0.5, "seed": 5,
                "dropout": 0.2, "history_dim": len(HISTORY_FEATURE_NAMES),
                "history_feature_names": list(HISTORY_FEATURE_NAMES), "history_mean": history_mean,
                "history_std": history_std}, checkpoint)
    out = tmp_path / "xai_history"
    assert explain_sample(record, "test", str(checkpoint), str(sample["clones"]), str(out), SETTINGS, 8, 0)[
        "status"] == "written"
    payload = json.loads((out / file_name(record["sample_id"])).read_text())
    layer = payload["layer_a"]
    assert sum(layer.values()) == pytest.approx(payload["logit"], abs=1e-5)
    assert payload["history_features"]["past_excess_growth"] == values["past_excess_growth"]


def test_ranking_metrics_roc_auc_and_top_20_percent_precision():
    from src.ml.hetero_gnn import binary_metrics
    labels = [1, 0, 1, 0, 0, 0, 0, 0, 1, 0]
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.1]
    metrics = binary_metrics(labels, scores, 0.65)
    # Positives at 0.9, 0.7, 0.1; negatives at 0.8 .. 0.1. Pairs won: 7 + 6 + 0.5 (tie) = 13.5 of 21.
    # Threshold 0.65 flags 0.9, 0.8, 0.7: 2 right + 6 correct "safe" = 8 of 10 correct.
    assert metrics["roc_auc"] == pytest.approx(13.5 / 21)
    assert metrics["precision_at_top_20pct"] == pytest.approx(0.5)     # top 2: 0.9 (risky), 0.8 (safe)
    assert metrics["accuracy"] == pytest.approx(0.8) and metrics["flagged_share"] == pytest.approx(0.3)
    assert binary_metrics([1, 0], [0.5, 0.5])["roc_auc"] == pytest.approx(0.5)


def test_late_fusion_weight_comes_from_validation_and_can_ignore_a_useless_model():
    import numpy as np
    from scripts.compare_coupling_models import _late_fusion
    labels = np.array([1, 0, 1, 0, 1, 0, 0, 0])
    good = np.array([0.9, 0.2, 0.8, 0.3, 0.7, 0.1, 0.2, 0.3])
    noise = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.9, 0.6])          # anti-correlated: must get no weight
    gnn = {s: good for s in ("train", "validation", "test")}
    diff = {s: noise for s in ("train", "validation", "test")}
    alpha, fused = _late_fusion(gnn, diff, labels)
    assert alpha == 1.0 and np.allclose(fused["test"], good, atol=1e-5)
