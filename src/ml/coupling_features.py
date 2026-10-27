"""Hand-made feature sets for the baselines the GNN is compared against (v5 dataset).

All features use only what exists before the PR is merged: the PR's diff, the repository
before the PR and the repository with the PR applied. Nothing from the outcome window.
"""
from __future__ import annotations

from datetime import datetime
import json
from math import log1p
from pathlib import Path
import re
from typing import Any

from src.dataset.structural_metrics import METRIC_NAMES

GRAPH_CHANGE_NAMES = ("added_node_count", "removed_node_count", "added_edge_count", "removed_edge_count",
                      "node_jaccard_distance", "edge_jaccard_distance")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_sample(record: dict[str, Any]) -> dict[str, Any]:
    folder = Path(record["_dir"])
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    diff = (folder / record.get("diff_path", "diff.patch")).read_text(encoding="utf-8", errors="replace")
    return {"metrics": metrics, "diff": diff}


def diff_lines(diff: str) -> tuple[list[str], list[str]]:
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    return added, removed


def shortcut_features(record: dict[str, Any], sample: dict[str, Any]) -> dict[str, float]:
    before = sample["metrics"]["before"]
    return {"merge_timestamp": datetime.fromisoformat(record["merged_at"]).timestamp() / 86400 / 365.25,
            "log_nodes": log1p(before["node_count"]), "log_edges": log1p(before["edge_count"]),
            "log_modules": log1p(before["module_count"])}


def change_size_features(record: dict[str, Any], sample: dict[str, Any]) -> dict[str, float]:
    """Kamei-style change metrics: how big and how spread the change is."""
    added, removed = diff_lines(sample["diff"])
    return {"log_lines_added": log1p(len(added)), "log_lines_removed": log1p(len(removed)),
            "log_files_changed": log1p(len(record["changed_python_files"])),
            "log_modules_touched": log1p(len(record["touched_modules"])),
            "hunk_count": log1p(sample["diff"].count("\n@@"))}


def structural_metric_features(record: dict[str, Any], sample: dict[str, Any]) -> dict[str, float]:
    """Mandatory 4 metrics: values before the PR and the PR's change in each, plus graph edit counts."""
    metrics = sample["metrics"]
    values: dict[str, float] = {}
    for name in METRIC_NAMES:
        values[f"before_{name}"] = float(metrics["before"][name])
        values[f"delta_{name}"] = float(metrics["delta"][name])
    for name in GRAPH_CHANGE_NAMES:
        values[f"change_{name}"] = float(metrics["change"][name])
    return values


def diff_tokens(sample: dict[str, Any]) -> str:
    """Bag-of-words document for JITLine-style models: added tokens and removed tokens kept apart."""
    added, removed = diff_lines(sample["diff"])
    plus = " ".join(f"A_{token}" for line in added for token in _TOKEN.findall(line))
    minus = " ".join(f"R_{token}" for line in removed for token in _TOKEN.findall(line))
    return f"{plus} {minus}"
