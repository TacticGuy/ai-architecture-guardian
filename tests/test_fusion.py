"""Fusion of GNN + CodeReviewer embeddings, on small synthetic data (no model download)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import torch

from src.fusion.data import AlignmentError, load_aligned, manifest_version
from src.fusion.evaluate import best_f1_threshold, bootstrap, score
from src.fusion.model import FusionModel, fit_projection
from src.ml.hetero_gnn import binary_metrics

ROOT = Path(__file__).resolve().parents[1]
SPLIT_SIZES = {"train": 30, "validation": 12, "test": 12}


def make_dataset(folder: Path, signal: str = "diff", seed: int = 0) -> dict[str, Path]:
    """Manifest + GNN store + CodeReviewer store. The label is readable from ``signal``'s vectors."""
    generator = torch.Generator().manual_seed(seed)
    rows, ids, labels, splits = [], [], [], []
    for split, size in SPLIT_SIZES.items():
        for i in range(size):
            sample_id = f"org/repo#{len(ids) + 100}"
            label = int(i % 3 != 0)                       # about two thirds risky, like the real data
            rows.append({"row_index": len(ids), "sample_id": sample_id, "label": label, "split": split})
            ids.append(sample_id), labels.append(label), splits.append(split)
    count = len(ids)
    gnn = torch.randn(count, 64, generator=generator)
    diff = torch.randn(count, 96, generator=generator)
    target = gnn if signal == "gnn" else diff
    target[:, 0] += 3.0 * (torch.tensor(labels, dtype=torch.float32) * 2 - 1)

    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "gnn_embeddings_v7.json"
    manifest.write_text(json.dumps({"embedding_file": "gnn_embeddings_v7.pt", "count": count, "rows": rows}),
                        encoding="utf-8")
    torch.save({"sample_ids": ids, "embeddings": gnn, "labels": torch.tensor(labels), "splits": splits},
               folder / "gnn_embeddings_v7.pt")
    diff_path = folder / "embeddings.pt"
    torch.save({"sample_ids": ids, "embeddings": diff, "labels": torch.tensor(labels), "splits": splits,
                "model_name": "fake/model",
                "manifest": {"sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}}, diff_path)
    return {"manifest": manifest, "gnn": folder / "gnn_embeddings_v7.pt", "diff": diff_path}


def rewrite(path: Path, **changes) -> None:
    store = torch.load(path, weights_only=True)
    store.update(changes)
    torch.save(store, path)


def load_script():
    spec = importlib.util.spec_from_file_location("train_fusion", ROOT / "scripts/train_fusion.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(paths: dict[str, Path], output: Path, *extra: str) -> int:
    return load_script().main(["--manifest", str(paths["manifest"]), "--diff", str(paths["diff"]),
                               "--output-dir", str(output), "--bootstrap", "200", *extra])


# --- joining by sample_id ----------------------------------------------------------------

def test_rows_are_joined_by_sample_id_not_by_position(tmp_path):
    paths = make_dataset(tmp_path)
    original = load_aligned(paths["manifest"], paths["gnn"], paths["diff"])
    store = torch.load(paths["diff"], weights_only=True)
    order = list(reversed(range(len(store["sample_ids"]))))
    rewrite(paths["diff"], sample_ids=[store["sample_ids"][i] for i in order], embeddings=store["embeddings"][order],
            labels=store["labels"][order], splits=[store["splits"][i] for i in order])
    shuffled = load_aligned(paths["manifest"], paths["gnn"], paths["diff"])
    assert shuffled.sample_ids == original.sample_ids
    assert torch.equal(shuffled.diff, original.diff) and torch.equal(shuffled.gnn, original.gnn)


@pytest.mark.parametrize("problem, message", [
    ("missing", "sample_ids differ from the manifest"),
    ("duplicate", "duplicate sample_ids"),
    ("label", "label of org/repo#100 is 1, manifest says 0"),
    ("split", "split of org/repo#100 is test, manifest says train"),
    ("nan", "NaN"),
])
def test_any_disagreement_with_the_manifest_stops_the_run(tmp_path, problem, message):
    paths = make_dataset(tmp_path)
    store = torch.load(paths["gnn"], weights_only=True)
    if problem == "missing":
        rewrite(paths["gnn"], sample_ids=store["sample_ids"][1:], embeddings=store["embeddings"][1:],
                labels=store["labels"][1:], splits=store["splits"][1:])
    elif problem == "duplicate":
        rewrite(paths["gnn"], sample_ids=[store["sample_ids"][1], *store["sample_ids"][1:]])
    elif problem == "label":
        labels = store["labels"].clone()
        labels[0] = 1
        rewrite(paths["gnn"], labels=labels)
    elif problem == "split":
        rewrite(paths["gnn"], splits=["test", *store["splits"][1:]])
    else:
        embeddings = store["embeddings"].clone()
        embeddings[3, 3] = float("nan")
        rewrite(paths["gnn"], embeddings=embeddings)
    with pytest.raises(AlignmentError, match=message):
        load_aligned(paths["manifest"], paths["gnn"], paths["diff"])
    assert run(paths, tmp_path / "out") == 2
    assert not (tmp_path / "out").exists()


def test_diff_vectors_built_for_another_manifest_are_refused(tmp_path):
    paths = make_dataset(tmp_path)
    rewrite(paths["diff"], manifest={"sha256": "0" * 64})
    with pytest.raises(AlignmentError, match="different manifest"):
        load_aligned(paths["manifest"], paths["gnn"], paths["diff"])


# --- PCA and the classifier ----------------------------------------------------------------

def test_pca_only_learns_from_training_rows(tmp_path):
    data = load_aligned(*make_dataset(tmp_path).values())
    train = data.indices("train")
    first = fit_projection(data.diff[train], 8)
    changed = data.diff.clone()
    changed[data.indices("test")] += 100.0                    # wildly different test rows
    second = fit_projection(changed[train], 8)
    assert torch.equal(first.components, second.components) and torch.equal(first.mean, second.mean)


def test_pca_never_uses_more_components_than_training_rows_allow():
    projection = fit_projection(torch.randn(5, 768, dtype=torch.float64), 8)
    assert projection.components.shape == (768, 4)            # 5 rows -> at most 4 components
    features = projection.transform(torch.randn(3, 768))
    assert features.shape == (3, 4)


def test_model_learns_a_real_signal_and_is_deterministic(tmp_path):
    data = load_aligned(*make_dataset(tmp_path, signal="diff").values())
    train, test = data.indices("train"), data.indices("test")
    matrices = {"gnn": data.gnn, "diff": data.diff}
    probabilities = []
    for _ in range(2):
        model = FusionModel(("gnn", "diff")).fit({k: v[train] for k, v in matrices.items()}, data.labels[train])
        probabilities.append(model.predict_proba(matrices))
    assert torch.equal(probabilities[0], probabilities[1])
    test_labels = data.labels[test].tolist()
    assert binary_metrics(test_labels, probabilities[0][test].tolist())["pr_auc_average_precision"] > 0.9


def test_mlp_option_trains_and_is_deterministic(tmp_path):
    data = load_aligned(*make_dataset(tmp_path, signal="gnn").values())
    train = data.indices("train")
    matrices = {"gnn": data.gnn, "diff": data.diff}
    outputs = [FusionModel(("gnn", "diff"), kind="mlp").fit({k: v[train] for k, v in matrices.items()},
                                                            data.labels[train]).predict_proba(matrices)
               for _ in range(2)]
    assert torch.equal(outputs[0], outputs[1]) and outputs[0].shape == (len(data.sample_ids),)


def test_training_needs_both_classes():
    with pytest.raises(ValueError, match="only one class"):
        FusionModel(("diff",)).fit({"diff": torch.randn(6, 10)}, torch.ones(6, dtype=torch.long))


# --- scoring -----------------------------------------------------------------------------

def test_threshold_rule_matches_the_gnn_training_script():
    labels, probabilities = [0, 1, 1, 0, 1], [0.2, 0.9, 0.4, 0.45, 0.7]
    threshold = best_f1_threshold(labels, probabilities)
    assert threshold == 0.4
    best = binary_metrics(labels, probabilities, threshold)["f1"]
    assert all(binary_metrics(labels, probabilities, t)["f1"] <= best for t in probabilities + [0.5])


def test_always_risky_baseline_scores_like_chance():
    labels = [1, 1, 0, 1, 0]
    metrics = score(labels, [1.0] * 5, 0.5, constant=True)
    assert metrics["recall"] == 1.0 and metrics["precision"] == 0.6
    assert metrics["pr_auc_average_precision"] == 0.6          # share of risky PRs, not a lucky tie-break
    assert binary_metrics(labels, [1.0] * 5)["pr_auc_average_precision"] == 0.6   # the GNN's metric agrees


def test_bootstrap_range_is_reproducible_and_contains_the_score():
    labels, probabilities = [1, 0, 1, 1, 0, 1, 0, 1], [0.9, 0.3, 0.8, 0.4, 0.6, 0.7, 0.2, 0.55]
    first = bootstrap(labels, probabilities, 0.5, 300, seed=1)
    assert first == bootstrap(labels, probabilities, 0.5, 300, seed=1)
    low, high = first["f1_95_range"]
    assert low <= binary_metrics(labels, probabilities, 0.5)["f1"] <= high


# --- the script --------------------------------------------------------------------------

def test_script_writes_metrics_predictions_and_a_reusable_model(tmp_path, capsys):
    paths, output = make_dataset(tmp_path / "artifacts"), tmp_path / "out"
    assert run(paths, output) == 0
    printed = capsys.readouterr().out
    assert "Joined 54 samples by sample_id" in printed and "train/validation/test = 30/12/12" in printed

    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["results"]) == {"always_risky", "gnn_only", "codereviewer_only", "fusion"}
    assert metrics["results"]["fusion"]["test"]["count"] == 12
    assert metrics["sources"]["gnn_embeddings"]["file"] == "gnn_embeddings_v7.pt"   # found via the manifest
    assert metrics["version"] == "v7"
    fusion_test = metrics["results"]["fusion"]["test"]["pr_auc_average_precision"]
    assert fusion_test > metrics["results"]["always_risky"]["test"]["pr_auc_average_precision"]

    with (output / "predictions.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 54 and {row["split"] for row in rows} == {"train", "validation", "test"}

    saved = torch.load(output / "fusion_model.pt", weights_only=True)          # safe loader works
    model = FusionModel.from_state(saved["models"][saved["main"]])
    data = load_aligned(paths["manifest"], paths["gnn"], paths["diff"])
    reloaded = model.predict_proba({"gnn": data.gnn, "diff": data.diff})
    assert torch.allclose(reloaded, torch.tensor([float(row["p_fusion"]) for row in rows], dtype=torch.float64),
                          atol=1e-6)
    assert model.threshold == metrics["results"]["fusion"]["threshold"]


def test_script_is_reproducible(tmp_path):
    paths = make_dataset(tmp_path / "artifacts")
    assert run(paths, tmp_path / "a") == 0 and run(paths, tmp_path / "b") == 0
    first = json.loads((tmp_path / "a/metrics.json").read_text(encoding="utf-8"))["results"]
    assert first == json.loads((tmp_path / "b/metrics.json").read_text(encoding="utf-8"))["results"]


def test_missing_codereviewer_vectors_explain_how_to_build_them(tmp_path, capsys):
    paths = make_dataset(tmp_path / "artifacts")
    paths["diff"].unlink()
    assert run(paths, tmp_path / "out") == 2
    assert "build_diff_embeddings.py --manifest" in capsys.readouterr().out


def test_version_comes_from_the_manifest_name():
    assert manifest_version(Path("artifacts/gnn_embeddings_v3.json")) == "v3"
    assert manifest_version(Path("artifacts/gnn_embeddings.json")) is None


def test_script_never_learns_from_validation_or_test_vectors(tmp_path):
    paths = make_dataset(tmp_path / "artifacts")
    assert run(paths, tmp_path / "a") == 0
    store = torch.load(paths["diff"], weights_only=True)
    embeddings = store["embeddings"].clone()
    unseen = [row for row, split in enumerate(store["splits"]) if split == "test"]
    embeddings[unseen] = torch.randn(len(unseen), embeddings.shape[1]) * 50          # scramble test vectors
    rewrite(paths["diff"], embeddings=embeddings)
    assert run(paths, tmp_path / "b") == 0
    first = torch.load(tmp_path / "a/fusion_model.pt", weights_only=True)["models"]["fusion"]
    second = torch.load(tmp_path / "b/fusion_model.pt", weights_only=True)["models"]["fusion"]
    assert first["threshold"] == second["threshold"]
    for key in first["params"]:
        assert torch.equal(first["params"][key], second["params"][key])
    for name in first["projections"]:
        for key in first["projections"][name]:
            assert torch.equal(first["projections"][name][key], second["projections"][name][key])
