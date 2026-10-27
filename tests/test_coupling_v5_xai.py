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
    clones = tmp_path / "clones"
    clones.mkdir()
    (clones / "o__r").symlink_to(history_repo, target_is_directory=True)
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
    assert layer["base"] + layer["structure_gnn"] + layer["diff"] == pytest.approx(payload["logit"], abs=1e-5)
    assert 0 < len(payload["top_edges"]) <= 30
    assert [abs(e["attribution"]) for e in payload["top_edges"]] == sorted(
        (abs(e["attribution"]) for e in payload["top_edges"]), reverse=True)
    added = [e for e in payload["top_edges"] if e["added_in_pr"]]
    assert all(e["relation"] != "CONTAINS" for e in added)
    assert payload["module_evidence"]["pkg.a"]["ce_after"] == payload["module_evidence"]["pkg.a"]["ce_before"] + 1
    assert 0.0 <= payload["unfaithfulness"] <= 1.0
    assert explain_sample(record, "test", str(checkpoint), str(sample["clones"]), str(out), SETTINGS, 16, 5)[
        "status"] == "existing"
