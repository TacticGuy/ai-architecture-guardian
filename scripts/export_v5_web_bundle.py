"""Write the v5 results in the file layout the web app and chatbot read (the v4 layout).

    python scripts/export_v5_web_bundle.py --manifest kaggle_v5_big/v5_manifest.jsonl \
        --comparison data/comparison_v51 --gnn-dir kaggle_v51/gnn_v51_small
    python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v5.json --samples-dir data/runs/coupling_samples_v5

Writes
  artifacts/gnn_embeddings_v5.json   which PRs exist, their labels and splits (the KB's manifest)
  artifacts/gnn_metrics_v5.json      repository-holdout split per repository + the baseline check
  data/fusion/v5/metrics.json        always-risky / GNN / CodeReviewer / fusion results (from the comparison)
  data/fusion/v5/predictions.csv     every PR's scores (p_fusion, p_gnn_only, p_codereviewer_only)
Nothing is recomputed: every number is copied from compare_coupling_models.py's results.json and
predictions.csv, so the web app shows exactly the comparison table's numbers.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "validation", "test")
SPLIT_NAMES = {"train": "train", "val": "validation", "validation": "validation", "test": "test"}
# web/KB model key -> comparison model key
MODEL_KEYS = {"always_risky": "always_risky", "gnn_only": "gnn", "codereviewer_only": "codereviewer_only",
              "fusion": "fusion_gnn_codereviewer"}


def read_manifest(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            rows.append({"sample_id": record["sample_id"], "repo": record["repo"], "label": int(record["label"]),
                         "split": SPLIT_NAMES[record["split"]]})
    return sorted(rows, key=lambda row: row["sample_id"])


def model_entry(result: dict) -> dict:
    entry = {split: result[split] for split in SPLITS if split in result}
    entry["threshold"] = result["threshold"]
    entry["description"] = result.get("description", "")
    entry["test_bootstrap"] = {"f1_95_range": result.get("test_f1_95"), "pr_auc_95_range": result.get("test_pr_auc_95")}
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True, help="v5_manifest.jsonl (export_v5_files.py)")
    parser.add_argument("--comparison", type=Path, required=True, help="output folder of compare_coupling_models.py")
    parser.add_argument("--gnn-dir", type=Path, required=True, help="the chosen GNN run (has metrics.json)")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    rows = read_manifest(args.manifest)
    results = json.loads((args.comparison / "results.json").read_text(encoding="utf-8"))
    with (args.comparison / "predictions.csv").open(encoding="utf-8") as handle:
        scores = {row["sample_id"]: row for row in csv.DictReader(handle)}
    missing = [key for key in MODEL_KEYS.values() if key not in results["models"]]
    if missing:
        raise SystemExit(f"The comparison has no {missing}; run compare_coupling_models.py with the GNN and embeddings")
    if {row["sample_id"] for row in rows} != set(scores):
        raise SystemExit("The comparison's predictions.csv and the manifest list different PRs")
    for row in rows:
        score = scores[row["sample_id"]]
        if int(score["label"]) != row["label"] or score["split"] != row["split"]:
            raise SystemExit(f"{row['sample_id']}: label or split differs between the manifest and the comparison")

    artifacts, fusion = args.root / "artifacts", args.root / "data/fusion/v5"
    artifacts.mkdir(parents=True, exist_ok=True)
    fusion.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps({"version": "v5", "label_protocol": "future_coupling_v1", "rows": rows}, indent=1)
                      + "\n").encode("utf-8")
    (artifacts / "gnn_embeddings_v5.json").write_bytes(manifest_bytes)

    gnn_run = json.loads((args.gnn_dir / "metrics.json").read_text(encoding="utf-8"))
    fusion_weight = results["models"]["fusion_gnn_codereviewer"]["description"]
    metrics = {
        "version": "v5",
        "sources": {"manifest": {"path": "artifacts/gnn_embeddings_v5.json",
                                 "sha256": hashlib.sha256(manifest_bytes).hexdigest()},
                    "comparison": str(args.comparison), "gnn_run": str(args.gnn_dir)},
        "results": {web: model_entry(results["models"][key]) for web, key in MODEL_KEYS.items()},
        "settings": {"model": "late fusion of log-odds", "pca_dims": 16,
                     "threshold_rule": "best F1 on the validation repositories",
                     "gnn": gnn_run.get("settings", {}), "gnn_seeds": gnn_run.get("seeds")},
        "warnings": [f"{fusion_weight}: validation gave the diff branch no weight, so fusion equals the GNN.",
                     "GNN scores are the mean of 5 seeds; edge explanations come from seed 1 alone."],
    }
    (fusion / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    with (fusion / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", "p_fusion", "p_gnn_only", "p_codereviewer_only"])
        for row in rows:
            score = scores[row["sample_id"]]
            writer.writerow([row["sample_id"], row["split"], row["label"], score["fusion_gnn_codereviewer"],
                             score["gnn"], score["codereviewer_only"]])

    cohort = {split: {"repositories": {}} for split in SPLITS}
    for row in rows:
        info = cohort[row["split"]]["repositories"].setdefault(row["repo"], {"total": 0, "risky": 0, "safe": 0})
        info["total"] += 1
        info["risky" if row["label"] else "safe"] += 1
    baselines = {key: {"test": value["test"], "feature_names": [value["description"]]}
                 for key, value in results["models"].items()
                 if key not in ("gnn",) and not key.startswith("fusion_")}
    best = max(baselines, key=lambda key: baselines[key]["test"]["pr_auc_average_precision"])
    gnn_ap = results["models"]["gnn"]["test"]["pr_auc_average_precision"]
    gnn_metrics = {
        "version": "v5", "split": "repository_holdout", "cohort": {"splits": cohort},
        "shortcut_baselines": baselines,
        "shortcut_check": {"gnn_test_pr_auc": gnn_ap, "best_baseline": best,
                           "best_baseline_test_pr_auc": baselines[best]["test"]["pr_auc_average_precision"],
                           "gnn_beats_best_baseline": gnn_ap > baselines[best]["test"]["pr_auc_average_precision"]},
        "status": "repository holdout, 5 seeds, settings chosen on validation",
    }
    (artifacts / "gnn_metrics_v5.json").write_text(json.dumps(gnn_metrics, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote the v5 web bundle for {len(rows)} PRs (GNN test PR-AUC {gnn_ap:.3f}).")
    print("Next: python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v5.json "
          "--samples-dir data/runs/coupling_samples_v5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
