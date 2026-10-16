"""Turn chat-API data into small tables for the web API. Pure functions, so they are easy to test.

The API reads everything through src/rag/api.py (Chatbot); these helpers only reshape.
"""
from __future__ import annotations

from typing import Any

MODEL_NAMES = {"always_risky": "Always risky (baseline)", "gnn_only": "GNN only",
               "codereviewer_only": "CodeReviewer only", "fusion": "Fusion"}


def results_table(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per model with its TEST scores and bootstrap ranges."""
    rows = []
    for key, name in MODEL_NAMES.items():
        result = metrics.get("results", {}).get(key)
        if not result:
            continue
        test, ranges = result["test"], result.get("test_bootstrap", {})
        rows.append({
            "Model": name, "F1": round(test["f1"], 3), "F1 range": _range(ranges.get("f1_95_range")),
            "Precision": round(test["precision"], 3), "Recall": round(test["recall"], 3),
            "PR-AUC": round(test["pr_auc_average_precision"], 3), "PR-AUC range": _range(ranges.get("pr_auc_95_range")),
            "TP": test["true_positive"], "FP": test["false_positive"], "TN": test["true_negative"],
            "FN": test["false_negative"]})
    return rows


def headline(metrics: dict[str, Any]) -> dict[str, Any]:
    """Fusion vs always-risky on the test split, for the stat tiles."""
    results = metrics.get("results", {})
    if "fusion" not in results or "always_risky" not in results:
        return {}
    fusion, baseline = results["fusion"]["test"], results["always_risky"]["test"]
    return {"fusion_f1": fusion["f1"], "baseline_f1": baseline["f1"],
            "fusion_ap": fusion["pr_auc_average_precision"], "baseline_ap": baseline["pr_auc_average_precision"],
            "threshold": results["fusion"]["threshold"], "test_prs": fusion["count"]}


def score_rows(predictions: list[dict[str, str]], split: str, threshold: float) -> list[dict[str, Any]]:
    """Every PR of one split with its fusion risk score, true label and whether the decision was right."""
    rows = []
    for row in predictions:
        if row["split"] != split:
            continue
        score, label = float(row["p_fusion"]), int(row["label"])
        predicted = int(score >= threshold)
        rows.append({"PR": f"#{row['sample_id'].split('#')[-1]}", "sample_id": row["sample_id"],
                     "Risk score": round(score, 3), "True label": "risky (1)" if label else "safe (0)",
                     "Prediction": "risky" if predicted else "not risky",
                     "Correct": "yes" if predicted == label else "no"})
    return sorted(rows, key=lambda item: -item["Risk score"])


def split_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    splits = summary.get("splits", {})
    for split in sorted(splits, key=lambda name: (["train", "validation", "test"] + [name]).index(name)):
        counts = splits[split]
        rows.append({"Split": split, "PRs": counts["prs"], "Risky (1)": counts["risky"],
                     "Safe (0)": counts["prs"] - counts["risky"]})
    return rows


def pr_label(meta: dict[str, Any], threshold: float) -> str:
    """Dropdown text, e.g. '#5648 · test · safe · risk 1.000 · WRONG · explained'."""
    correct = int(meta["probability"] >= threshold) == meta["label"]
    return (f"#{meta['pr_number']} · {meta['split']} · {'risky' if meta['label'] else 'safe'} · "
            f"risk {meta['probability']:.3f} · {'correct' if correct else 'WRONG'}"
            f"{' · explained' if meta.get('explained') else ''}")


def layer_a_rows(explanation: dict[str, Any]) -> list[dict[str, Any]]:
    parts = explanation["contributions"]
    rows = [("Base (average PR)", parts["base_logit"]), ("Structure (GNN)", parts["structure_gnn"]),
            ("Diff (CodeReviewer)", parts["diff_codereviewer"])]
    return [{"Part": name, "Logit": round(value, 3), "Direction": "pushes risk up" if value >= 0 else "pushes risk down"}
            for name, value in rows]


def layer_b_rows(explanation: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    return [{"File": hunk["file"], "Lines": f"{hunk['new_lines'][0]}-{hunk['new_lines'][1]}",
             "Effect on risk": round(hunk["effect_on_risk"], 4), "Added": hunk["added"], "Removed": hunk["removed"],
             "snippet": "\n".join(hunk.get("snippet", []))} for hunk in explanation.get("hunks", [])[:limit]]


def layer_c_rows(explanation: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    graph = explanation.get("graph") or {}
    return [{"File": row["file"], "Effect": round(row["attribution"], 3),
             "Touched by PR": "touched" if row["touched"] else "not touched", "Nodes": row["nodes"]}
            for row in graph.get("files", [])[:limit]]


def _range(values: list[float] | None) -> str:
    return f"{values[0]:.2f}–{values[1]:.2f}" if values else "–"
