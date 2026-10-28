"""Compare the GNN with every baseline on the same held-out repositories (v5 dataset).

    python scripts/compare_coupling_models.py --data-dir data/coupling_samples_v5

Every model is trained on the training repositories, gets its threshold from the validation
repositories (best F1) and is scored once on the test repositories. Optional inputs are used
when they exist:
  data/gnn_v5/seed_*/predictions.csv and embeddings.pt      GNN scores and vectors
  data/embeddings_v5/<model>.pt                              {sample_id: vector} diff embeddings
  data/tool_metrics_v5.jsonl                                  Pylint / Radon / SonarQube numbers
Writes data/comparison_v5/results.json, results.md and predictions.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from scipy.sparse import hstack, csr_matrix  # noqa: E402

from src.ml.coupling_data import discover_coupling_samples  # noqa: E402
from src.ml.coupling_features import (  # noqa: E402
    change_size_features, diff_tokens, history_feature_table, read_sample, shortcut_features,
    structural_metric_features,
)
from src.ml.hetero_gnn import binary_metrics  # noqa: E402

SPLITS = ("train", "validation", "test")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/coupling_samples_v5")
    parser.add_argument("--split", type=Path, default=ROOT / "config/coupling_split_v5.json")
    parser.add_argument("--gnn-dir", type=Path, default=ROOT / "data/gnn_v5")
    parser.add_argument("--embeddings-dir", type=Path, default=ROOT / "data/embeddings_v5")
    parser.add_argument("--tool-metrics", type=Path, nargs="+", default=[ROOT / "data/tool_metrics_v5.jsonl"],
                        help="one or more jsonl files ({'sample_id', 'tool.metric': number}), merged by sample_id")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/comparison_v5")
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)

    records = discover_coupling_samples(args.data_dir)
    split = json.loads(args.split.read_text(encoding="utf-8"))
    where = {repo: name for name, repos in split.items() for repo in repos}
    rows = {name: [r for r in records if where.get(r["repo"]) == name] for name in SPLITS}
    samples = {r["sample_id"]: read_sample(r) for r in records}
    labels = {name: np.array([r["label"] for r in rows[name]]) for name in SPLITS}
    ids = {name: [r["sample_id"] for r in rows[name]] for name in SPLITS}

    def table(builder):
        out = {}
        for name in SPLITS:
            dicts = [builder(r, samples[r["sample_id"]]) for r in rows[name]]
            keys = sorted(dicts[0])
            out[name] = np.array([[d[k] for k in keys] for d in dicts], dtype=float)
        return out

    def combine(*tables):
        return {name: np.hstack([t[name] for t in tables]) for name in SPLITS}

    scores: dict[str, dict[str, np.ndarray]] = {}
    descriptions: dict[str, str] = {}

    def fit(name, description, model, features):
        model.fit(features["train"], labels["train"])
        scores[name] = {s: model.predict_proba(features[s])[:, 1] for s in SPLITS}
        descriptions[name] = description

    linear = lambda: make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=3000))  # noqa: E731
    shortcuts, size, structure = table(shortcut_features), table(change_size_features), table(structural_metric_features)
    scores["always_risky"] = {s: np.ones(len(rows[s])) for s in SPLITS}
    descriptions["always_risky"] = "Calls every PR degrading"
    fit("shortcut_date_size", "Merge date + repository size (logistic regression)", linear(), shortcuts)
    fit("change_size_lr", "Kamei-style change size: lines, files, hunks, modules (logistic regression)", linear(), size)
    fit("structural_metrics_lr", "Graph metrics before + PR change: density, centrality, clustering, entropy, "
        "cycles (logistic regression)", linear(), combine(structure, size))
    fit("structural_metrics_gb", "Same graph + size metrics (gradient boosting)",
        GradientBoostingClassifier(random_state=0), combine(structure, size))

    if all(samples[i]["history"] is not None for s in SPLITS for i in ids[s]):
        # v5.1: the same pre-merge history the GNN gets, so the comparison stays fair.
        history = table(history_feature_table)
        fit("history_lr", "Pre-merge history: coupling momentum + change activity (logistic regression)", linear(), history)
        fit("history_gb", "Pre-merge history (gradient boosting)", GradientBoostingClassifier(random_state=0), history)
        fit("structure_history_gb", "Graph metrics + change size + pre-merge history (gradient boosting)",
            GradientBoostingClassifier(random_state=0), combine(structure, size, history))
    else:
        print("history.json missing for some samples: history baselines skipped")

    vectorizer = TfidfVectorizer(token_pattern=r"\S+", min_df=3, max_features=20000, sublinear_tf=True)
    vectorizer.fit([diff_tokens(samples[i]) for i in ids["train"]])
    jit = {s: hstack([vectorizer.transform([diff_tokens(samples[i]) for i in ids[s]]), csr_matrix(size[s])]).tocsr()
           for s in SPLITS}
    fit("jitline_rf", "JITLine-style: diff bag-of-words + change size (random forest)",
        RandomForestClassifier(n_estimators=300, class_weight="balanced_subsample", random_state=0, n_jobs=-1), jit)

    tools, test_only_tools = _tool_features(args.tool_metrics, ids)
    for tool, features in tools.items():
        fit(f"{tool}_lr", f"{tool} metrics of the touched files (logistic regression)",
            make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(class_weight="balanced", max_iter=3000)), features)
    fixed_thresholds: dict[str, float] = {}
    # Industry-style quality gate, fixed in advance (no training): SonarQube flags a PR that adds
    # technical debt (sqale_index = estimated minutes of remediation work).
    gate = _tool_column(args.tool_metrics, "sonar.delta_sqale_index", ids)
    if gate is not None and not np.isnan(gate["test"]).any():
        scores["sonar_debt_gate_rule"] = {s: 1.0 / (1.0 + np.exp(-np.nan_to_num(gate[s], nan=0.0))) for s in SPLITS}
        descriptions["sonar_debt_gate_rule"] = "SonarQube quality gate: flag the PR if it adds technical debt (fixed rule)"
        fixed_thresholds["sonar_debt_gate_rule"] = float(1.0 / (1.0 + np.exp(-0.5)))
    subset_rules: dict[str, tuple[str, np.ndarray, np.ndarray]] = {}
    for tool, columns in test_only_tools.items():
        # A tool run on the test PRs only (SonarQube: too slow for every PR) cannot train a model.
        # Its rule is fixed in advance: "flag the PR if it increases this measure" (score > 0).
        for key, values in columns.items():
            name = f"{key.replace('.', '_')}_rule"
            covered = ~np.isnan(values)
            fixed_thresholds[name] = float(1.0 / (1.0 + np.exp(-0.5)))
            rule = {"test": 1.0 / (1.0 + np.exp(-np.nan_to_num(values, nan=0.0)))}
            if covered.all():
                scores[name] = rule
                descriptions[name] = f"{key} > 0 flags the PR (fixed rule, test PRs only)"
            else:
                subset_rules[name] = (f"{key} > 0 flags the PR (fixed rule)", rule["test"], covered)

    gnn = _gnn_scores(args.gnn_dir, ids)
    if gnn is not None:
        scores["gnn"], descriptions["gnn"] = gnn, "Heterogeneous GNN (ours, mean of seeds)"
    diff_vectors = {path.stem: _embedding_table(path, ids) for path in sorted(args.embeddings_dir.glob("*.pt"))}
    for model_name, vectors in diff_vectors.items():
        if vectors is None:
            continue
        fit(f"{model_name}_only", f"{model_name} diff embedding only (PCA + logistic regression)",
            make_pipeline(StandardScaler(), PCA(16, random_state=0), LogisticRegression(class_weight="balanced", max_iter=3000)),
            vectors)
        if gnn is not None:
            # Late fusion: mix the GNN's score (structure + history) with the diff model's score.
            # The weight is chosen on validation only; alpha = 1 means the diff adds nothing.
            alpha, fused = _late_fusion(scores["gnn"], scores[f"{model_name}_only"], labels["validation"])
            scores[f"fusion_gnn_{model_name}"] = fused
            descriptions[f"fusion_gnn_{model_name}"] = (f"Late fusion: {alpha:.2f} x GNN + {1 - alpha:.2f} x {model_name} "
                                                       "(log-odds; weight chosen on validation)")

    results = {"split": split, "counts": {s: {"prs": len(rows[s]), "degrading": int(labels[s].sum())} for s in SPLITS},
               "models": {}}
    rng = np.random.default_rng(42)
    boot = [rng.integers(0, len(rows["test"]), len(rows["test"])) for _ in range(args.bootstrap)]
    for name, predicted in scores.items():
        if name in fixed_thresholds:
            threshold = fixed_thresholds[name]
        else:
            threshold = _best_threshold(labels["validation"], predicted["validation"])
        entry = {"description": descriptions[name], "threshold": threshold}
        for s in SPLITS:
            if s in predicted:
                entry[s] = binary_metrics(labels[s].tolist(), predicted[s].clip(0, 1).tolist(), threshold)
        f1s, aps = [], []
        for index in boot:
            metrics = binary_metrics(labels["test"][index].tolist(), predicted["test"][index].clip(0, 1).tolist(), threshold)
            f1s.append(metrics["f1"]); aps.append(metrics["pr_auc_average_precision"])
        entry["test_f1_95"] = [float(np.percentile(f1s, 2.5)), float(np.percentile(f1s, 97.5))]
        entry["test_pr_auc_95"] = [float(np.percentile(aps, 2.5)), float(np.percentile(aps, 97.5))]
        results["models"][name] = entry
    if "gnn" in scores:
        results["gnn_vs_baselines"] = _paired_comparison(scores, labels["test"], boot, "gnn")
    # Tools run on part of the test split: compare with the GNN on exactly the same PRs.
    gnn_threshold = results["models"].get("gnn", {}).get("threshold")
    for name, (description, rule_scores, covered) in subset_rules.items():
        subset_labels = labels["test"][covered].tolist()
        entry = {"description": description, "test_prs": int(covered.sum()),
                 "degrading": int(sum(subset_labels)),
                 "rule": binary_metrics(subset_labels, rule_scores[covered].tolist(), fixed_thresholds[name])}
        if "gnn" in scores:
            entry["gnn_same_prs"] = binary_metrics(subset_labels, scores["gnn"]["test"][covered].clip(0, 1).tolist(),
                                                   gnn_threshold)
        results.setdefault("test_subset_comparisons", {})[name] = entry
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "results.md").write_text(_markdown(results), encoding="utf-8")
    with (args.output_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", *scores])
        for s in SPLITS:
            for index, sample_id in enumerate(ids[s]):
                writer.writerow([sample_id, s, int(labels[s][index]),
                                 *(f"{scores[m][s][index]:.6f}" if s in scores[m] else "" for m in scores)])
    print(_markdown(results))
    return 0


def _late_fusion(gnn: dict, diff: dict, validation_labels: np.ndarray) -> tuple[float, dict]:
    def logit(values: np.ndarray) -> np.ndarray:
        clipped = np.clip(values, 1e-6, 1 - 1e-6)
        return np.log(clipped / (1 - clipped))

    def mix(alpha: float, split: str) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(alpha * logit(gnn[split]) + (1 - alpha) * logit(diff[split]))))

    grid = [round(step * 0.05, 2) for step in range(21)]
    best = max(grid, key=lambda a: (binary_metrics(validation_labels.tolist(), mix(a, "validation").tolist())[
        "pr_auc_average_precision"], a))           # ties go to the larger GNN weight
    return best, {split: mix(best, split) for split in SPLITS}


def _best_threshold(labels: np.ndarray, scores: np.ndarray) -> float:
    candidates = sorted(set([0.5, *scores.clip(0, 1).tolist()]))
    return max(candidates, key=lambda t: (binary_metrics(labels.tolist(), scores.clip(0, 1).tolist(), t)["f1"], -abs(t - 0.5)))


def _paired_comparison(scores, labels, boot, ours) -> dict:
    """Share of bootstrap resamples where our PR-AUC beats each baseline's (paired: same PRs)."""
    out = {}
    for name, predicted in scores.items():
        if name == ours:
            continue
        wins = []
        for index in boot:
            mine = binary_metrics(labels[index].tolist(), scores[ours]["test"][index].clip(0, 1).tolist())["pr_auc_average_precision"]
            theirs = binary_metrics(labels[index].tolist(), predicted["test"][index].clip(0, 1).tolist())["pr_auc_average_precision"]
            wins.append(mine - theirs)
        wins = np.array(wins)
        out[name] = {"mean_pr_auc_difference": float(wins.mean()), "share_of_resamples_gnn_better": float((wins > 0).mean())}
    return out


def _gnn_scores(gnn_dir: Path, ids) -> dict | None:
    files = sorted(gnn_dir.glob("seed_*/predictions.csv"))
    if not files:
        return None
    per_sample: dict[str, list[float]] = {}
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                per_sample.setdefault(row["sample_id"], []).append(float(row["score"]))
    return {s: np.array([np.mean(per_sample[i]) for i in ids[s]]) for s in SPLITS}


def _gnn_embeddings(gnn_dir: Path, ids):
    import torch
    files = sorted(gnn_dir.glob("seed_*/embeddings.pt"))
    if not files:
        return None
    vectors = torch.load(files[0], weights_only=False)
    return {s: np.stack([vectors[i].numpy() for i in ids[s]]) for s in SPLITS}


def _embedding_table(path: Path, ids):
    import torch
    vectors = torch.load(path, weights_only=False)
    if not all(i in vectors for s in SPLITS for i in ids[s]):
        print(f"{path.name}: missing samples, skipped")
        return None
    return {s: np.stack([np.asarray(vectors[i], dtype=float) for i in ids[s]]) for s in SPLITS}


def _tool_features(paths, ids) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, np.ndarray]]]:
    """Tool numbers from ``tool_metrics_v5.jsonl`` ({"sample_id", "tool.metric": number or null}).

    Returns (tools measured on every PR -> feature tables per split,
             tools measured on every test PR only -> {"tool.metric": test values}).
    A tool missing some PRs it should cover is skipped with a message; single nulls (the tool
    failed on that PR) become NaN and are imputed with the training median.
    """
    rows: dict[str, dict] = {}
    for path in ([paths] if isinstance(paths, Path) else paths):
        if not path.is_file():
            print(f"{path}: not found, skipped")
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows.setdefault(row["sample_id"], {}).update(row)
    if not rows:
        return {}, {}

    def has(sample_id: str, tool: str) -> bool:
        row = rows.get(sample_id, {})
        return any(key.startswith(f"{tool}.") and row[key] is not None for key in row)

    def value(sample_id: str, key: str) -> float:
        raw = rows.get(sample_id, {}).get(key)
        return float("nan") if raw is None else float(raw)

    full: dict[str, dict[str, np.ndarray]] = {}
    test_only: dict[str, dict[str, np.ndarray]] = {}
    for tool in sorted({key.split(".", 1)[0] for row in rows.values() for key in row if "." in key}):
        keys = sorted({key for row in rows.values() for key in row if key.startswith(f"{tool}.")})
        every = [i for s in SPLITS for i in ids[s]]
        if sum(has(i, tool) for i in every) >= 0.99 * len(every):
            # Measured on (almost) every PR; the few PRs where the tool failed are imputed.
            full[tool] = {s: np.array([[value(i, k) for k in keys] for i in ids[s]]) for s in SPLITS}
        elif any(has(i, tool) for i in ids["test"]):
            # NaN marks test PRs the tool was not run on; those rules are scored on the covered PRs only.
            test_only[tool] = {k: np.array([value(i, k) if has(i, tool) else float("nan") for i in ids["test"]])
                               for k in keys if k.split(".", 1)[1].startswith("delta_")}
        else:
            print(f"{tool}: not measured on any test PR, skipped")
    return full, test_only


def _tool_column(paths, key: str, ids):
    values: dict[str, float] = {}
    for path in paths:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get(key) is not None:
                        values[row["sample_id"]] = float(row[key])
    if not values:
        return None
    return {s: np.array([values.get(i, np.nan) for i in ids[s]]) for s in SPLITS}


def _markdown(results: dict) -> str:
    lines = ["| Model | Test PR-AUC (95% range) | ROC-AUC | Precision in top 20% | Accuracy | F1 (95% range) | Precision | Recall | Flags |",
             "|---|---|---|---|---|---|---|---|---|"]
    order = sorted(results["models"].items(), key=lambda item: -item[1]["test"]["pr_auc_average_precision"])
    for name, entry in order:
        test = entry["test"]
        lines.append(f"| {name} | {test['pr_auc_average_precision']:.3f} ({entry['test_pr_auc_95'][0]:.2f}-{entry['test_pr_auc_95'][1]:.2f}) | "
                     f"{test['roc_auc']:.3f} | {test['precision_at_top_20pct']:.3f} | {test['accuracy']:.3f} | "
                     f"{test['f1']:.3f} ({entry['test_f1_95'][0]:.2f}-{entry['test_f1_95'][1]:.2f}) | "
                     f"{test['precision']:.3f} | {test['recall']:.3f} | {test['flagged_share']:.0%} |")
    shown_gnn_subsets = set()
    for name, entry in results.get("test_subset_comparisons", {}).items():
        gnn = entry.get("gnn_same_prs")
        rows = [(f"{name} (on {entry['test_prs']} test PRs)", entry["rule"])]
        if gnn and entry["test_prs"] not in shown_gnn_subsets:
            shown_gnn_subsets.add(entry["test_prs"])
            rows.append((f"gnn (same {entry['test_prs']} PRs)", gnn))
        for label, metrics in rows:
            if metrics:
                lines.append(f"| {label} | {metrics['pr_auc_average_precision']:.3f} | {metrics['roc_auc']:.3f} | "
                             f"{metrics['precision_at_top_20pct']:.3f} | {metrics['accuracy']:.3f} | {metrics['f1']:.3f} | "
                             f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | {metrics['flagged_share']:.0%} |")
    counts = results["counts"]
    lines.append("")
    lines.append("PRs: " + ", ".join(f"{s} {counts[s]['prs']} ({counts[s]['degrading']} degrading)" for s in SPLITS))
    share = counts["test"]["degrading"] / max(counts["test"]["prs"], 1)
    lines.append(f"Chance level on test: PR-AUC and precision in top 20% = {share:.3f}, ROC-AUC = 0.500. "
                 "Accuracy and F1 depend on the threshold (chosen on validation); 'Flags' is the share of test PRs called degrading.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
