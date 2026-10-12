"""XAI layer C: which code files drive the structure (GNN) part of the fusion score.

The GNN here is the project's real HeteroRiskGNN class on a small real code graph (built by
the Step 2-5 pipeline from a tiny package); only its weights are random, because training is
not what is being tested. The last test uses the teammate's REAL v3 checkpoint and graphs when
they are on this machine, and is skipped elsewhere.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest
import torch

from src.fusion.model import FusionModel, Projection
from src.ml.gnn_data import attach_touched_masks
from src.ml.gnn_inference import load_gnn_checkpoint, load_gnn_model, prepare_graph
from src.ml.hetero_data import TENSOR_FEATURE_NAMES, build_hetero_data, save_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN
from src.xai.explain import ExplanationError
from src.xai.graph import explain_graph
from tests.test_diff_encoder import FakeModel, FakeTokenizer
from tests.test_hetero_data import make_package

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = 8


def code_graph(tmp_path: Path):
    result = make_package(tmp_path / "package")
    return attach_touched_masks(build_hetero_data(result["graph"], result["features"]), ["src/pkg/core.py"])


def checkpoint_for(graph, seed: int = 0) -> dict:
    torch.manual_seed(seed)
    model = HeteroRiskGNN(graph.metadata(), len(TENSOR_FEATURE_NAMES), HIDDEN)
    return {"model_state_dict": model.state_dict(), "metadata": graph.metadata(),
            "feature_names": list(TENSOR_FEATURE_NAMES), "feature_mean": torch.zeros(len(TENSOR_FEATURE_NAMES)),
            "feature_std": torch.ones(len(TENSOR_FEATURE_NAMES)), "hidden_channels": HIDDEN, "threshold": 0.5}


def fusion_model(seed: int = 3) -> FusionModel:
    generator = torch.Generator().manual_seed(seed)
    model = FusionModel(("gnn", "diff"))
    model.projections = {
        "gnn": Projection(torch.zeros(2 * HIDDEN, dtype=torch.float64),
                          torch.randn(2 * HIDDEN, 3, generator=generator, dtype=torch.float64),
                          torch.ones(3, dtype=torch.float64)),
        "diff": Projection(torch.zeros(4, dtype=torch.float64), torch.eye(4, 1, dtype=torch.float64),
                           torch.ones(1, dtype=torch.float64))}
    model.params = {"weight": torch.tensor([2.0, -1.5, 1.0, 0.5], dtype=torch.float64),
                    "bias": torch.tensor([0.1], dtype=torch.float64)}
    return model


def prepared(tmp_path: Path, seed: int = 0):
    graph = code_graph(tmp_path)
    path = tmp_path / "before" / "graph.pt"
    save_hetero_data(graph, path)
    checkpoint = checkpoint_for(graph, seed)
    gnn = load_gnn_model(checkpoint, "cpu")
    ready = prepare_graph(path, checkpoint)
    with torch.no_grad():
        stored = gnn.encode(ready)[0]
    return gnn, ready, stored


def run_layer_c(gnn, graph, stored, **extra):
    return explain_graph(gnn=gnn, graph=graph, fusion=fusion_model(), diff=torch.ones(4), stored_gnn=stored,
                         feature_names=list(TENSOR_FEATURE_NAMES), **extra)


# --- the method --------------------------------------------------------------------------------

def test_file_scores_add_up_to_the_total_change(tmp_path):
    gnn, graph, stored = prepared(tmp_path)
    result = run_layer_c(gnn, graph, stored, top_files=100)
    assert result["completeness_error"] <= max(0.01, 0.02 * abs(result["total_change"]))
    assert abs(sum(row["attribution"] for row in result["files"]) - result["total_change"]) <= 0.02
    assert abs(result["touched_files_total"] + result["untouched_files_total"]
               - sum(row["attribution"] for row in result["files"])) < 1e-9


def test_nodes_are_grouped_by_file_and_touched_files_are_marked(tmp_path):
    gnn, graph, stored = prepared(tmp_path)
    files = {row["file"]: row for row in run_layer_c(gnn, graph, stored, top_files=100)["files"]}
    assert set(files) == {"src/pkg/__init__.py", "src/pkg/base.py", "src/pkg/core.py",
                          "(external modules)", "(external callables)"}
    assert [name for name, row in files.items() if row["touched"]] == ["src/pkg/core.py"]
    assert files["src/pkg/core.py"]["nodes"] == 4                 # module, Engine, helper, Engine.run
    assert files["src/pkg/base.py"]["nodes"] == 3


def test_a_file_that_already_looks_average_gets_zero(tmp_path):
    gnn, graph, _ = prepared(tmp_path)
    for node_type in graph.node_types:                              # make base.py exactly "average"
        for row, node_id in enumerate(graph[node_type].node_ids):
            if node_id.startswith("src/pkg/base.py:"):
                graph[node_type].x[row] = 0.0
    with torch.no_grad():
        stored = gnn.encode(graph)[0]
    files = {row["file"]: row for row in run_layer_c(gnn, graph, stored, top_files=100)["files"]}
    assert files["src/pkg/base.py"]["attribution"] == 0.0
    assert any(row["attribution"] != 0.0 for name, row in files.items() if name != "src/pkg/base.py")


def test_wrong_checkpoint_is_refused(tmp_path):
    gnn, graph, stored = prepared(tmp_path, seed=0)
    other = load_gnn_model(checkpoint_for(code_graph(tmp_path / "again"), seed=1), "cpu")
    with pytest.raises(ExplanationError, match="does not reproduce the saved GNN vector"):
        run_layer_c(other, graph, stored)


def test_layer_c_is_deterministic_and_leaves_the_graph_alone(tmp_path):
    gnn, graph, stored = prepared(tmp_path)
    before = {node_type: graph[node_type].x.clone() for node_type in graph.node_types}
    assert run_layer_c(gnn, graph, stored) == run_layer_c(gnn, graph, stored)
    assert all(torch.equal(before[node_type], graph[node_type].x) for node_type in graph.node_types)


# --- the script, end to end -------------------------------------------------------------------

def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_factory(model_name, settings, device):
    from src.semantic.diff_encoder import DiffEncoder
    return DiffEncoder(FakeTokenizer(), FakeModel(), model_name, settings, device)


def build_everything(tmp_path: Path) -> dict[str, Path]:
    """Samples with diff + graph -> GNN vectors from a checkpoint -> diff vectors -> fusion."""
    base_graph = code_graph(tmp_path / "source")
    checkpoint = checkpoint_for(base_graph, seed=0)
    gnn = load_gnn_model(checkpoint, "cpu")
    samples, artifacts = tmp_path / "samples", tmp_path / "artifacts"
    artifacts.mkdir()
    torch.save(checkpoint, artifacts / "gnn_future_risk_v9.pt")
    rows, vectors = [], []
    plan = ["train"] * 8 + ["validation"] * 4 + ["test"] * 4
    for number, split in enumerate(plan, 1):
        label, folder = number % 2, samples / "org__r" / str(number)
        graph = base_graph.clone()
        graph["module"].x = graph["module"].x * (1 + number)            # each PR's code differs a bit
        save_hetero_data(graph, folder / "before" / "graph.pt")
        body = "\n".join(["+DANGER"] * 6 if label else ["+calm = 1"])
        (folder / "diff.patch").write_text(f"diff --git a/src/pkg/m.py b/src/pkg/m.py\n--- a/src/pkg/m.py\n"
                                           f"+++ b/src/pkg/m.py\n@@ -1,1 +1,2 @@\n+v{number} = 0\n{body}\n",
                                           encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps({"sample_id": f"org/r#{number}", "label": label,
                                                          "diff_path": "diff.patch",
                                                          "before_graph_path": "before/graph.pt"}), encoding="utf-8")
        with torch.no_grad():
            vectors.append(gnn.encode(prepare_graph(folder / "before" / "graph.pt", checkpoint))[0])
        rows.append({"row_index": number - 1, "sample_id": f"org/r#{number}", "label": label, "split": split})
    manifest = artifacts / "gnn_embeddings_v9.json"
    manifest.write_text(json.dumps({"embedding_file": "gnn_embeddings_v9.pt", "checkpoint_name": "gnn_future_risk_v9.pt",
                                    "count": len(rows), "rows": rows}), encoding="utf-8")
    torch.save({"sample_ids": [row["sample_id"] for row in rows], "embeddings": torch.stack(vectors),
                "labels": torch.tensor([row["label"] for row in rows]), "splits": [row["split"] for row in rows]},
               artifacts / "gnn_embeddings_v9.pt")
    assert load("build_diff_embeddings").main(["--manifest", str(manifest), "--samples-dir", str(samples),
                                               "--output-dir", str(tmp_path / "emb"), "--model", "fake/model"],
                                              encoder_factory=fake_factory) == 0
    assert load("train_fusion").main(["--manifest", str(manifest), "--diff", str(tmp_path / "emb/embeddings.pt"),
                                      "--output-dir", str(tmp_path / "fusion"), "--bootstrap", "0",
                                      "--pca-dims", "3"]) == 0
    return {"manifest": manifest, "samples": samples, "diff": tmp_path / "emb/embeddings.pt",
            "fusion": tmp_path / "fusion/fusion_model.pt", "xai": tmp_path / "xai", "base_graph": base_graph}


def explain_script(paths: dict, *extra: str) -> int:
    return load("explain_prs").main(["--manifest", str(paths["manifest"]), "--diff", str(paths["diff"]),
                                     "--fusion-model", str(paths["fusion"]), "--samples-dir", str(paths["samples"]),
                                     "--output-dir", str(paths["xai"]), "--max-hunks", "2", *extra],
                                    encoder_factory=fake_factory)


def test_script_adds_layer_c_with_the_checkpoint_named_in_the_manifest(tmp_path, capsys):
    paths = build_everything(tmp_path)
    assert explain_script(paths) == 0
    assert "Layer C: GNN checkpoint gnn_future_risk_v9.pt" in capsys.readouterr().out
    report = json.loads((paths["xai"] / "org__r__13.json").read_text(encoding="utf-8"))
    graph = report["graph"]
    assert graph["files"] and graph["completeness_error"] <= max(0.01, 0.02 * abs(graph["total_change"]))
    assert 0.0 <= graph["gnn_probability"] <= 1.0
    with (paths["xai"] / "summary.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4 and all(row["top_file"] for row in rows)


def test_script_stops_when_the_checkpoint_does_not_match(tmp_path, capsys):
    paths = build_everything(tmp_path)
    wrong = tmp_path / "wrong.pt"
    torch.save(checkpoint_for(paths["base_graph"], seed=7), wrong)
    assert explain_script(paths, "--gnn-checkpoint", str(wrong)) == 1
    assert "does not reproduce the saved GNN vector" in capsys.readouterr().out


def test_missing_checkpoint_explains_how_to_continue(tmp_path, capsys):
    paths = build_everything(tmp_path)
    (paths["manifest"].parent / "gnn_future_risk_v9.pt").unlink()
    assert explain_script(paths) == 2
    assert "--no-graph" in capsys.readouterr().out
    assert explain_script(paths, "--no-graph") == 0


# --- optional: the teammate's real v3 checkpoint on this machine -------------------------------------

REAL = {"checkpoint": ROOT / "artifacts/gnn_future_risk_v3.pt", "manifest": ROOT / "artifacts/gnn_embeddings_v3.json",
        "gnn": ROOT / "artifacts/gnn_embeddings_v3.pt", "samples": ROOT / "data/future_pr_samples_v3",
        "diff": ROOT / "data/embeddings/microsoft__codereviewer__gnn_embeddings_v3/embeddings.pt",
        "fusion": ROOT / "data/fusion/v3/fusion_model.pt"}


def test_real_v3_checkpoint_reproduces_vectors_and_explains_a_pr():
    missing = [name for name, path in REAL.items() if not path.exists()]
    if missing:
        pytest.skip(f"real v3 files not on this machine: {', '.join(missing)}")
    from src.fusion.data import load_aligned
    data = load_aligned(REAL["manifest"], REAL["gnn"], REAL["diff"])
    checkpoint = load_gnn_checkpoint(REAL["checkpoint"])
    gnn = load_gnn_model(checkpoint, "cpu")
    saved = torch.load(REAL["fusion"], weights_only=True)
    fusion = FusionModel.from_state(saved["models"][saved["main"]])
    row = data.indices("test")[0]
    repo, number = data.sample_ids[row].split("#")
    graph = prepare_graph(REAL["samples"] / repo.replace("/", "__") / number / "before/graph.pt", checkpoint)
    result = explain_graph(gnn=gnn, graph=graph, fusion=fusion, diff=data.diff[row], stored_gnn=data.gnn[row],
                           feature_names=list(checkpoint["feature_names"]))
    assert result["files"] and result["completeness_error"] <= max(0.01, 0.02 * abs(result["total_change"]))
