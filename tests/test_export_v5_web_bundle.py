"""v5 results in the web app's layout, and v5-aware chatbot cards (label text + edge explanations)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.export_v5_web_bundle import main as export_main
from src.rag.knowledge import build_cards, load_inputs

SPLITS = ("train", "validation", "test")


def _metrics(f1: float, ap: float, count: int = 2) -> dict:
    return {"count": count, "positives": 1, "threshold": 0.5, "true_positive": 1, "false_positive": 0,
            "true_negative": 1, "false_negative": 0, "precision": 1.0, "recall": 1.0, "f1": f1,
            "pr_auc_average_precision": ap}


def _bundle(tmp_path: Path) -> dict[str, Path]:
    ids = {"train": "o/a#1", "validation": "o/b#2", "test": "o/c#3"}
    manifest = tmp_path / "v5_manifest.jsonl"
    manifest.write_text("".join(json.dumps({"sample_id": sample_id, "repo": sample_id.split("#")[0], "label": 1,
                                            "split": "val" if split == "validation" else split}) + "\n"
                                for split, sample_id in ids.items()), encoding="utf-8")
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    models = {}
    for key, ap in (("always_risky", 0.38), ("gnn", 0.63), ("codereviewer_only", 0.40),
                    ("fusion_gnn_codereviewer", 0.63), ("hotspot_lr", 0.61)):
        models[key] = {"description": "Late fusion: 1.00 x GNN + 0.00 x codereviewer" if key.startswith("fusion")
                       else key, "threshold": 0.5, "test_f1_95": [0.5, 0.6], "test_pr_auc_95": [0.59, 0.67],
                       **{split: _metrics(0.6, ap) for split in SPLITS}}
    (comparison / "results.json").write_text(json.dumps({"models": models}), encoding="utf-8")
    with (comparison / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", *models])
        for split, sample_id in ids.items():
            writer.writerow([sample_id, split, 1, "1.0", "0.7", "0.4", "0.7", "0.6"])
    gnn_dir = tmp_path / "gnn"
    gnn_dir.mkdir()
    (gnn_dir / "metrics.json").write_text(json.dumps({"settings": {"hidden_channels": 32}, "seeds": [1, 2]}),
                                          encoding="utf-8")
    samples = tmp_path / "samples"
    for split, sample_id in ids.items():
        folder = samples / sample_id.split("#")[0].replace("/", "__") / sample_id.split("#")[1]
        folder.mkdir(parents=True)
        (folder / "metadata.json").write_text(json.dumps({
            "sample_id": sample_id, "label_protocol": "future_coupling_v1", "label": 1,
            "label_reason": "excess_coupling_growth", "excess_growth": 1.25, "horizon_months": 6,
            "merged_at": "2024-01-02T00:00:00+00:00", "changed_python_files": ["pkg/x.py"]}), encoding="utf-8")
    xai = tmp_path / "xai"
    xai.mkdir()
    (xai / "o__c__3.json").write_text(json.dumps({
        "schema": "attribution_v5/1", "sample_id": "o/c#3", "label": 1, "risk_score": 0.66,
        "layer_a": {"base": -0.2, "structure_gnn": 0.3, "history": 0.5, "diff": 0.0},
        "top_edges": [{"source": "pkg/x.py:pkg.x.run", "relation": "CALLS", "target": "pkg/y.py:pkg.y.load",
                       "attribution": 0.42, "added_in_pr": True},
                      {"source": "pkg/x.py:pkg.x", "relation": "IMPORTS", "target": "pkg/z.py:pkg.z",
                       "attribution": -0.1, "added_in_pr": False}],
        "top_hunks": [{"file": "pkg/x.py", "lines": [3, 9], "effect": 0.05}], "new_cycle_modules": [],
        "unfaithfulness": 0.0001}), encoding="utf-8")
    return {"manifest": manifest, "comparison": comparison, "gnn": gnn_dir, "samples": samples, "xai": xai}


def test_export_then_cards_describe_the_v5_label_and_edges(tmp_path):
    paths = _bundle(tmp_path)
    root = tmp_path / "root"
    assert export_main(["--manifest", str(paths["manifest"]), "--comparison", str(paths["comparison"]),
                        "--gnn-dir", str(paths["gnn"]), "--root", str(root)]) == 0
    manifest = json.loads((root / "artifacts/gnn_embeddings_v5.json").read_text())
    assert {row["split"] for row in manifest["rows"]} == set(SPLITS)          # "val" became "validation"
    metrics = json.loads((root / "data/fusion/v5/metrics.json").read_text())
    assert metrics["results"]["gnn_only"]["test"]["pr_auc_average_precision"] == 0.63
    assert metrics["results"]["fusion"]["test_bootstrap"]["pr_auc_95_range"] == [0.59, 0.67]
    gnn_metrics = json.loads((root / "artifacts/gnn_metrics_v5.json").read_text())
    assert gnn_metrics["shortcut_check"]["best_baseline"] == "hotspot_lr"
    assert gnn_metrics["shortcut_check"]["gnn_beats_best_baseline"] is True

    inputs = load_inputs(manifest_path=root / "artifacts/gnn_embeddings_v5.json", fusion_dir=root / "data/fusion/v5",
                         xai_dir=paths["xai"], samples_dir=paths["samples"],
                         gnn_metrics_path=root / "artifacts/gnn_metrics_v5.json")
    cards = {card.id: card for card in build_cards(inputs, None)}
    explained = cards["pr:o/c#3"].text
    assert "gained dependency links faster than the project's own trend" in explained
    assert "+1.25" in explained and "reviewed architecture refactor" not in explained.lower()
    assert "pkg.x.run CALLS pkg.y.load (+0.420, new in this PR)" in explained
    assert "pre-merge history +0.50" in explained and "IMPORTS" not in explained   # only edges pushing risk up
    assert cards["pr:o/c#3"].meta["explained"] is True
    assert "not been explained yet" in cards["pr:o/a#1"].text


def test_export_refuses_a_comparison_that_lists_other_prs(tmp_path):
    paths = _bundle(tmp_path)
    with paths["manifest"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"sample_id": "o/d#4", "repo": "o/d", "label": 0, "split": "test"}) + "\n")
    try:
        export_main(["--manifest", str(paths["manifest"]), "--comparison", str(paths["comparison"]),
                     "--gnn-dir", str(paths["gnn"]), "--root", str(tmp_path / "root")])
    except SystemExit as exc:
        assert "different PRs" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_pr_details_keeps_v5_attributions_out_of_the_v4_explorer(tmp_path):
    from src.rag.api import Chatbot
    from src.rag.knowledge import Card
    (tmp_path / "data/xai/v5").mkdir(parents=True)
    (tmp_path / "data/xai/v5/o__c__3.json").write_text(json.dumps({"schema": "attribution_v5/1", "sample_id": "o/c#3"}),
                                                     encoding="utf-8")
    card = Card(id="pr:o/c#3", kind="pr", title="PR o/c#3", text="...", meta={"sample_id": "o/c#3", "label": 1,
                                                                            "probability": 0.7, "split": "test"})
    details = Chatbot([card], llm=None, top_k=3, version="v5", root=tmp_path).pr_details("o/c#3")
    assert details["explanation"] is None and details["attribution_v5"]["schema"] == "attribution_v5/1"
