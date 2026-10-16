"""Train and evaluate the fusion model (GNN vectors + CodeReviewer vectors).

    python scripts/train_fusion.py --manifest artifacts/gnn_embeddings_v3.json

Finds the other inputs from the manifest:
  GNN vectors          artifacts/<embedding_file named in the manifest>   (gnn_embeddings_v3.pt)
  CodeReviewer vectors data/embeddings/microsoft__codereviewer__gnn_embeddings_v3/embeddings.pt
Writes data/fusion/<version>/:
  metrics.json      four models side by side (always-risky baseline, GNN only, CodeReviewer only,
                    fusion) with validation + test scores and a bootstrap range on test
  predictions.csv   sample_id, split, label and each model's probability
  fusion_model.pt   the fitted models (PCA + classifier + threshold) to score new PRs later

Rules: rows are joined by sample_id only; PCA and the classifier see the TRAIN rows only;
the threshold is picked on VALIDATION (best F1, same rule as the GNN); TEST is used once.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from src.fusion.data import AlignedData, AlignmentError, load_aligned, manifest_version  # noqa: E402
from src.fusion.evaluate import best_f1_threshold, bootstrap, score  # noqa: E402
from src.fusion.model import FusionModel  # noqa: E402

SCHEMA_VERSION = 1
VARIANTS = {"gnn_only": ("gnn",), "codereviewer_only": ("diff",), "fusion": ("gnn", "diff")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the GNN + CodeReviewer fusion model.")
    parser.add_argument("--manifest", type=Path, required=True, help="e.g. artifacts/gnn_embeddings_v3.json")
    parser.add_argument("--gnn", type=Path, help="GNN embeddings .pt (default: the file named in the manifest)")
    parser.add_argument("--diff", type=Path, help="CodeReviewer embeddings.pt (default: data/embeddings/...)")
    parser.add_argument("--diff-model", default="microsoft/codereviewer", help="Model used for the diff vectors")
    parser.add_argument("--gnn-metrics", type=Path, help="GNN training metrics to show for reference "
                                                          "(default: gnn_metrics_<version>.json next to the manifest)")
    parser.add_argument("--output-dir", type=Path, help="Default: data/fusion/<version>")
    parser.add_argument("--model", choices=("logreg", "mlp"), default="logreg",
                        help="logreg (default, right for tiny data) or mlp (one hidden layer, for more data)")
    parser.add_argument("--pca-dims", type=int, default=8, help="PCA numbers kept per input (capped at train rows - 1)")
    parser.add_argument("--c", type=float, default=1.0, help="Logistic regression strength (smaller = simpler model)")
    parser.add_argument("--bootstrap", type=int, default=1000, help="Resamples for the test ranges (0 = off)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.pca_dims < 1 or args.c <= 0 or args.bootstrap < 0:
        parser.error("--pca-dims must be >= 1, --c > 0 and --bootstrap >= 0")

    version = manifest_version(args.manifest) or args.manifest.stem
    gnn_path = args.gnn or _default_gnn_path(args.manifest)
    diff_path = args.diff or (ROOT / "data/embeddings"
                              / f"{args.diff_model.replace('/', '__')}__{args.manifest.stem}" / "embeddings.pt")
    output_dir = args.output_dir or ROOT / "data/fusion" / version
    for name, path in (("manifest", args.manifest), ("GNN embeddings", gnn_path), ("CodeReviewer embeddings", diff_path)):
        if not path.is_file():
            hint = (" Run: python scripts/build_diff_embeddings.py --manifest " + str(args.manifest)
                    if name == "CodeReviewer embeddings" else "")
            print(f"Missing {name}: {path}.{hint}")
            return 2

    try:
        data = load_aligned(args.manifest, gnn_path, diff_path)
    except AlignmentError as exc:
        print(f"Inputs do not line up: {exc}")
        return 2
    counts = data.sources["split_counts"]
    print(f"Joined {len(data.sample_ids)} samples by sample_id | GNN dim {data.gnn.shape[1]} | "
          f"CodeReviewer dim {data.diff.shape[1]} | train/validation/test = "
          f"{counts.get('train', 0)}/{counts.get('validation', 0)}/{counts.get('test', 0)}")

    try:
        results, models, probabilities = run_all_variants(data, args)
    except ValueError as exc:
        print(f"Cannot train: {exc}")
        return 2

    reference = _reference_gnn_metrics(args.gnn_metrics, args.manifest, version)
    report = {
        "schema_version": SCHEMA_VERSION, "version": version, "sources": data.sources,
        "settings": {"model": args.model, "pca_dims": args.pca_dims, "c": args.c,
                     "bootstrap": args.bootstrap, "seed": args.seed,
                     "threshold_rule": "best F1 on validation (same as the GNN)"},
        "results": results, "warnings": _warnings(data, results),
    }
    if reference is not None:
        report["gnn_reported_by_training"] = reference
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "metrics.json", report)
    _write_predictions(output_dir / "predictions.csv", data, probabilities, results["fusion"]["threshold"])
    _atomic_save(output_dir / "fusion_model.pt", {
        "schema_version": SCHEMA_VERSION, "version": version, "main": "fusion", "sources": data.sources,
        "models": {name: model.to_state() for name, model in models.items()}})

    _print_table(results, reference)
    for warning in report["warnings"]:
        print(f"Note: {warning}")
    print(f"Saved: {output_dir / 'metrics.json'}\n       {output_dir / 'predictions.csv'}\n"
          f"       {output_dir / 'fusion_model.pt'}")
    return 0


def run_all_variants(data: AlignedData, args: Any) -> tuple[dict[str, Any], dict[str, FusionModel], dict[str, list[float]]]:
    """Fit every variant on the train rows, pick its threshold on validation, score it on test."""
    train, validation, test = (data.indices(split) for split in ("train", "validation", "test"))
    labels = data.labels.tolist()
    matrices = {"gnn": data.gnn, "diff": data.diff}
    pick = lambda rows: [labels[row] for row in rows]  # noqa: E731

    results: dict[str, Any] = {}
    validation_ones, test_ones = [1.0] * len(validation), [1.0] * len(test)
    results["always_risky"] = {
        "inputs": [], "threshold": 0.5,
        "validation": score(pick(validation), validation_ones, 0.5, constant=True),
        "test": score(pick(test), test_ones, 0.5, constant=True),
        "test_bootstrap": bootstrap(pick(test), test_ones, 0.5, args.bootstrap, args.seed, constant=True)}

    models: dict[str, FusionModel] = {}
    probabilities: dict[str, list[float]] = {}
    for name, inputs in VARIANTS.items():
        model = FusionModel(inputs, args.model, args.pca_dims, args.c, args.seed)
        model.fit({key: value[train] for key, value in matrices.items()}, data.labels[train])
        all_probabilities = model.predict_proba(matrices).tolist()
        model.threshold = best_f1_threshold(pick(validation), [all_probabilities[row] for row in validation])
        test_probabilities = [all_probabilities[row] for row in test]
        results[name] = {
            "inputs": list(inputs), "threshold": model.threshold,
            "pca_dims_used": {key: int(projection.components.shape[1]) for key, projection in model.projections.items()},
            "train": score(pick(train), [all_probabilities[row] for row in train], model.threshold),
            "validation": score(pick(validation), [all_probabilities[row] for row in validation], model.threshold),
            "test": score(pick(test), test_probabilities, model.threshold),
            "test_bootstrap": bootstrap(pick(test), test_probabilities, model.threshold, args.bootstrap, args.seed)}
        models[name], probabilities[name] = model, all_probabilities
    return results, models, probabilities


def _default_gnn_path(manifest_path: Path) -> Path:
    try:
        named = json.loads(manifest_path.read_text(encoding="utf-8")).get("embedding_file")
    except (OSError, json.JSONDecodeError):
        named = None
    return manifest_path.parent / named if isinstance(named, str) and named else manifest_path.with_suffix(".pt")


def _reference_gnn_metrics(path: Path | None, manifest_path: Path, version: str) -> dict[str, Any] | None:
    path = path or manifest_path.parent / f"gnn_metrics_{version}.json"
    if not path.is_file():
        return None
    try:
        test = json.loads(path.read_text(encoding="utf-8")).get("test")
    except (OSError, json.JSONDecodeError):
        return None
    return {"file": path.name, "test": test} if isinstance(test, dict) else None


def _warnings(data: AlignedData, results: dict[str, Any]) -> list[str]:
    notes = []
    for split in ("train", "validation", "test"):
        rows = data.indices(split)
        negatives = sum(1 for row in rows if int(data.labels[row]) == 0)
        if negatives < 3:
            notes.append(f"{split} has only {negatives} safe (label 0) PR(s); its scores are not reliable.")
    fusion, baseline = results["fusion"]["test"], results["always_risky"]["test"]
    if fusion["pr_auc_average_precision"] <= baseline["pr_auc_average_precision"]:
        notes.append("Fusion does not rank test PRs better than chance (PR-AUC <= share of risky PRs).")
    if len(data.indices("test")) < 30:
        notes.append(f"Only {len(data.indices('test'))} test PRs: use the bootstrap ranges, not single numbers.")
    return notes


def _print_table(results: dict[str, Any], reference: dict[str, Any] | None) -> None:
    print("\nTEST results (threshold picked on validation)")
    print(f"{'model':<20}{'F1':>6}{'prec':>7}{'recall':>8}{'PR-AUC':>8}   F1 range      PR-AUC range")
    for name, result in results.items():
        test, ranges = result["test"], result["test_bootstrap"]
        f1_range = _fmt_range(ranges.get("f1_95_range"))
        ap_range = _fmt_range(ranges.get("pr_auc_95_range"))
        print(f"{name:<20}{test['f1']:>6.2f}{test['precision']:>7.2f}{test['recall']:>8.2f}"
              f"{test['pr_auc_average_precision']:>8.3f}   {f1_range:<14}{ap_range}")
    if reference:
        test = reference["test"]
        print(f"{'(GNN as trained)':<20}{test.get('f1', 0):>6.2f}{test.get('precision', 0):>7.2f}"
              f"{test.get('recall', 0):>8.2f}{test.get('pr_auc_average_precision', 0):>8.3f}   "
              f"from {reference['file']}")
    print()


def _fmt_range(values: list[float] | None) -> str:
    return f"{values[0]:.2f}-{values[1]:.2f}" if values else "-"


def _write_predictions(path: Path, data: AlignedData, probabilities: dict[str, list[float]], threshold: float) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", *(f"p_{name}" for name in VARIANTS), "fusion_prediction"])
        for row, sample_id in enumerate(data.sample_ids):
            fused = probabilities["fusion"][row]
            writer.writerow([sample_id, data.splits[row], int(data.labels[row]),
                             *(f"{probabilities[name][row]:.6f}" for name in VARIANTS), int(fused >= threshold)])
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_save(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(value, temporary)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
