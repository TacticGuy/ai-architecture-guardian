"""Chatbot knowledge base: cards built only from the project's output files."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.rag.knowledge import KnowledgeError, build_cards, load_cards, load_inputs

ROOT = Path(__file__).resolve().parents[1]

ROWS = [("o/r#10", 1, "train"), ("o/r#11", 0, "train"), ("o/r#20", 1, "validation"), ("o/r#21", 0, "validation"),
        ("o/r#30", 1, "test"), ("o/r#31", 0, "test"), ("o/r#32", 0, "test")]
SCORES = {"o/r#10": 0.9, "o/r#11": 0.1, "o/r#20": 0.8, "o/r#21": 0.3, "o/r#30": 0.7654321, "o/r#31": 0.2, "o/r#32": 0.6}
THRESHOLD = 0.5


def explanation(sample_id: str, label: int, split: str) -> dict:
    return {"sample_id": sample_id, "label": label, "split": split, "probability": SCORES[sample_id],
            "threshold": THRESHOLD, "predicted_risky": SCORES[sample_id] >= THRESHOLD,
            "contributions": {"base_logit": 1.1, "structure_gnn": -0.284, "diff_codereviewer": 0.337,
                              "logit": 1.153, "probability": SCORES[sample_id], "exact": True},
            "hunks": [{"file": "src/pkg/a.py", "new_lines": [207, 218], "added": 6, "removed": 13,
                       "effect_on_risk": 0.1042, "snippet": ["-import warnings", "+x = 1"]}],
            "hunk_counts": {"total": 3, "in_analysed_files": 2, "explained": 1, "skipped_by_cap": 1},
            "graph": {"files": [{"file": "src/pkg/a.py", "attribution": 2.69, "touched": True, "nodes": 4},
                                {"file": "src/pkg/cli.py", "attribution": 1.46, "touched": False, "nodes": 9}],
                      "touched_files_total": 3.56, "untouched_files_total": 5.42, "gnn_probability": 0.815}}


def make_project(root: Path, explained=("o/r#30",)) -> dict[str, Path]:
    artifacts, fusion, xai, samples, docs = (root / name for name in ("artifacts", "fusion", "xai", "samples", "docs"))
    for folder in (artifacts, fusion, xai, samples, docs):
        folder.mkdir(parents=True, exist_ok=True)
    manifest = artifacts / "gnn_embeddings_v7.json"
    manifest.write_text(json.dumps({"count": len(ROWS), "rows": [
        {"row_index": i, "sample_id": sid, "label": label, "split": split} for i, (sid, label, split) in enumerate(ROWS)]}),
        encoding="utf-8")
    result = lambda f1: {"threshold": THRESHOLD, "test": {  # noqa: E731
        "f1": f1, "precision": 0.6, "recall": 1.0, "pr_auc_average_precision": 0.577, "true_positive": 1,
        "false_positive": 2, "true_negative": 0, "false_negative": 0, "count": 3, "positives": 1},
        "validation": {"f1": 0.974, "pr_auc_average_precision": 0.992, "count": 2, "positives": 1},
        "test_bootstrap": {"f1_95_range": [0.5, 0.93], "pr_auc_95_range": [0.35, 1.0]}}
    metrics = {"version": "v7", "sources": {"manifest": {"sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}},
               "settings": {"model": "logreg", "pca_dims": 8, "threshold_rule": "best F1 on validation"},
               "results": {"always_risky": result(0.75), "gnn_only": result(0.7), "codereviewer_only": result(0.6),
                           "fusion": result(0.75)},
               "gnn_reported_by_training": {"test": {"f1": 0.783, "precision": 0.643, "recall": 1.0,
                                                      "pr_auc_average_precision": 0.549}},
               "warnings": ["validation has only 1 safe (label 0) PR(s); its scores are not reliable."]}
    (fusion / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    with (fusion / "predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", "p_gnn_only", "p_codereviewer_only", "p_fusion", "fusion_prediction"])
        for sid, label, split in ROWS:
            writer.writerow([sid, split, label, "0.604000", "0.736000", f"{SCORES[sid]:.6f}", int(SCORES[sid] >= THRESHOLD)])
    for sid, label, split in ROWS:
        if sid in explained:
            (xai / f"{sid.replace('/', '__').replace('#', '__')}.json").write_text(
                json.dumps(explanation(sid, label, split)), encoding="utf-8")
    for sid, label, _ in [*ROWS, ("o/r#25", 1, "purged"), ("o/r#5", 1, "purged")]:
        folder = samples / "o__r" / sid.split("#")[1]
        folder.mkdir(parents=True, exist_ok=True)
        record = {"sample_id": sid, "label": label, "merged_at": "2023-02-23T17:34:18Z", "horizon_months": 6,
                  "changed_python_files": ["src/pkg/a.py"]}
        if label:
            record.update({"triggering_refactor_pr": "o/r#99", "triggering_refactor_merged_at": "2023-08-20T16:32:09+00:00",
                           "matched_python_files": ["src/pkg/a.py"],
                           "event_evidence": {"rationale": "Split App into Sans-IO base classes."}})
        (folder / "metadata.json").write_text(json.dumps(record), encoding="utf-8")
    (artifacts / "gnn_metrics_v7.json").write_text(json.dumps(
        {"cutoffs": {"train": "2021-05-05T23:59:59Z", "validation": "2023-02-01T00:00:00Z"}}), encoding="utf-8")
    (docs / "README.md").write_text("# About\n\n## Ignored\nnot a card\n", encoding="utf-8")
    (docs / "xai.md").write_text("# XAI\n\n## Layer A: structure\nSplits the score.\nInto two parts.\n\n"
                                 "## Layer B\nHides one hunk at a time.\n", encoding="utf-8")
    return {"manifest": manifest, "fusion": fusion, "xai": xai, "samples": samples, "docs": docs,
            "gnn_metrics": artifacts / "gnn_metrics_v7.json", "out": root / "kb"}


def cards_of(paths: dict[str, Path]) -> dict[str, object]:
    inputs = load_inputs(manifest_path=paths["manifest"], fusion_dir=paths["fusion"], xai_dir=paths["xai"],
                         samples_dir=paths["samples"], gnn_metrics_path=paths["gnn_metrics"])
    return {card.id: card for card in build_cards(inputs, paths["docs"])}


# --- what the cards say -------------------------------------------------------------------------

def test_one_card_per_pr_plus_tables_model_dataset_and_docs(tmp_path):
    cards = cards_of(make_project(tmp_path))
    assert sorted(card_id for card_id in cards if card_id.startswith("pr:")) == sorted(f"pr:{sid}" for sid, _, _ in ROWS)
    assert {"dataset", "model:fusion", "predictions:train", "predictions:validation", "predictions:test"} <= set(cards)
    assert {card_id for card_id in cards if card_id.startswith("doc:")} == {"doc:xai#layer-a-structure", "doc:xai#layer-b"}
    assert cards["doc:xai#layer-a-structure"].text == "Splits the score. Into two parts."


def test_explained_pr_card_carries_label_evidence_scores_and_all_three_layers(tmp_path):
    text = cards_of(make_project(tmp_path))["pr:o/r#30"].text
    assert "True label: 1 (risky). Reviewed architecture refactor o/r#99 merged 2023-08-20" in text
    assert "Reviewer rationale: Split App into Sans-IO base classes." in text
    assert "Fusion risk score 0.765 (threshold 0.500): predicted risky, which is correct." in text
    assert "structure from the GNN -0.28, diff from CodeReviewer +0.34" in text
    assert "src/pkg/a.py lines 207-218 (effect +0.104; +6/-13 lines)" in text
    assert "src/pkg/cli.py +1.46 (not touched)" in text and "untouched files total +5.42" in text
    assert "In words: files this PR did NOT touch moved the structure score more than the files it touched " \
           "(+5.42 vs +3.56)" in text


def test_unexplained_and_safe_pr_cards_say_so(tmp_path):
    cards = cards_of(make_project(tmp_path))
    assert "has not been explained yet" in cards["pr:o/r#11"].text
    assert "True label: 0 (safe)" in cards["pr:o/r#32"].text
    assert cards["pr:o/r#32"].text.splitlines()[1] == ("Summary: true label 0 (safe); fusion predicted risky with "
                                                      "risk score 0.600, which is WRONG.")
    assert "predicted risky, which is wrong" in cards["pr:o/r#32"].text          # 0.6 >= 0.5 but label 0


def test_prediction_table_counts_outcomes_with_the_threshold(tmp_path):
    text = cards_of(make_project(tmp_path))["predictions:test"].text
    assert "o/r#31: label 0, risk 0.200, not risky (true negative)" in text
    assert "Totals: true positive 1, false positive 1, true negative 1, false negative 0." in text


def test_model_and_dataset_cards_copy_the_real_numbers(tmp_path):
    cards = cards_of(make_project(tmp_path))
    model = cards["model:fusion"].text
    assert "Always risky (baseline): F1 0.750 (range 0.50-0.93)" in model
    assert "The GNN's own reported test result (from its training run): F1 0.783" in model
    assert "Warning: validation has only 1 safe" in model
    dataset = cards["dataset"].text
    assert "test: 3 PRs, 1 risky (label 1), 2 safe (label 0)." in dataset
    assert "Purged (removed because their six-month window crosses a split cutoff): 2 PRs: o/r#5, o/r#25." in dataset
    assert "train outcomes known by 2021-05-05" in dataset


# --- the inputs must agree --------------------------------------------------------------------

def test_fusion_results_from_another_manifest_are_refused(tmp_path):
    paths = make_project(tmp_path)
    metrics = json.loads((paths["fusion"] / "metrics.json").read_text(encoding="utf-8"))
    metrics["sources"]["manifest"]["sha256"] = "0" * 64
    (paths["fusion"] / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="different manifest"):
        cards_of(paths)


def test_explanation_from_another_fusion_run_is_refused(tmp_path):
    paths = make_project(tmp_path)
    path = paths["xai"] / "o__r__30.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["probability"] = 0.5
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="risk score differs"):
        cards_of(paths)


def test_predictions_must_match_the_manifest(tmp_path):
    paths = make_project(tmp_path)
    lines = (paths["fusion"] / "predictions.csv").read_text(encoding="utf-8").splitlines()
    (paths["fusion"] / "predictions.csv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="does not cover exactly"):
        cards_of(paths)


# --- the script ---------------------------------------------------------------------------------

def run(paths: dict[str, Path], *extra: str) -> int:
    spec = importlib.util.spec_from_file_location("build_kb", ROOT / "scripts/build_kb.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(["--manifest", str(paths["manifest"]), "--fusion-dir", str(paths["fusion"]),
                        "--xai-dir", str(paths["xai"]), "--samples-dir", str(paths["samples"]),
                        "--docs-dir", str(paths["docs"]), "--output-dir", str(paths["out"]), *extra])


def test_script_writes_the_same_cards_every_time(tmp_path, capsys):
    paths = make_project(tmp_path)
    assert run(paths) == 0
    assert "PR cards with explanations: 1 of 7" in capsys.readouterr().out
    first = (paths["out"] / "cards.jsonl").read_bytes()
    assert run(paths) == 0
    assert (paths["out"] / "cards.jsonl").read_bytes() == first
    assert len(load_cards(paths["out"] / "cards.jsonl")) == 7 + 3 + 2 + 2
    info = json.loads((paths["out"] / "kb.json").read_text(encoding="utf-8"))
    assert info["cards"] == 14 and info["sources"]["explained_prs"] == ["o/r#30"]


def test_script_needs_the_fusion_outputs(tmp_path, capsys):
    paths = make_project(tmp_path)
    (paths["fusion"] / "metrics.json").unlink()
    assert run(paths) == 2
    assert "Run scripts/train_fusion.py first" in capsys.readouterr().out


# --- optional: the real v3 outputs on this machine ---------------------------------------------------

def test_real_v3_knowledge_base_matches_the_real_outputs():
    manifest = ROOT / "artifacts/gnn_embeddings_v3.json"
    fusion = ROOT / "data/fusion/v3"
    if not (manifest.is_file() and (fusion / "metrics.json").is_file()):
        pytest.skip("real v3 fusion outputs not on this machine")
    inputs = load_inputs(manifest_path=manifest, fusion_dir=fusion, xai_dir=ROOT / "data/xai/v3",
                         samples_dir=ROOT / "data/future_pr_samples_v3",
                         gnn_metrics_path=ROOT / "artifacts/gnn_metrics_v3.json")
    cards = {card.id: card for card in build_cards(inputs, ROOT / "docs/knowledge")}
    assert sum(card_id.startswith("pr:") for card_id in cards) == len(inputs["rows"])
    fusion_test = inputs["metrics"]["results"]["fusion"]["test"]
    assert f"Fusion: F1 {fusion_test['f1']:.3f}" in cards["model:fusion"].text
