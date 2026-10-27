"""Build the v5 dataset: one sample per merged PR with an automatic future-coupling label.

For each PR the repository is analysed three times with the unchanged Steps 2-4:
  * BEFORE: the first parent of the landing commit (code just before the PR),
  * AT MERGE: the landing commit (the PR applied; its code exists before merge, so this
    is fair model input),
  * FUTURE: the last first-parent commit at the end of the month that is ``horizon`` months
    after the merge (cached per commit, because many PRs share it).

Saved per sample (small files only; full analysis JSON would be gigabytes):
  graph.pt        AT-MERGE HeteroData + ``touched_mask`` + ``delta`` (new node, gained and lost
                  dependency edges) per node, for the GNN
  diff.patch      the PR's Python diff, for CodeBERT/CodeReviewer
  metrics.json    before/after structural metrics (density, centrality, clustering, entropy...)
  label.json      the future-coupling label and its numbers
  metadata.json   identity, dates, files, label
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import calendar
import json
from pathlib import Path
import subprocess
from typing import Any

import torch

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.analysis.features import create_node_features
from src.dataset.cycle_labels import create_cycle_label
from src.dataset.future_coupling import (
    coupling_summary, future_coupling_label, node_delta_features, touched_module_names,
)
from src.dataset.future_refactor_labels import add_calendar_months
from src.dataset.pr_history import MergedPR, changed_paths, commit_at_or_before, production_python_files
from src.dataset.structural_metrics import compare_structural_metrics
from src.ml.gnn_data import attach_touched_masks
from src.ml.hetero_data import build_hetero_data, save_hetero_data

SCHEMA_VERSION = 1
DELTA_FEATURE_NAMES = ("is_new_in_pr", "dependency_edges_gained", "dependency_edges_lost")


class SampleSkipped(RuntimeError):
    """The PR is valid but cannot be labelled or analysed (reason in the message)."""


@dataclass
class Snapshotter:
    """One reusable scratch worktree per repository: switching commits is much cheaper than
    creating and deleting a worktree for every snapshot."""
    repository: Path
    worktree: Path

    def __post_init__(self) -> None:
        if not (self.worktree / ".git").exists():
            self.worktree.parent.mkdir(parents=True, exist_ok=True)
            _git(self.repository, "-c", "core.longpaths=true", "worktree", "add", "--detach", "--force",
                 str(self.worktree), "HEAD")

    def checkout(self, sha: str) -> Path:
        _git(self.worktree, "checkout", "--quiet", "--force", "--detach", sha)
        _git(self.worktree, "clean", "-fdxq")
        return self.worktree


def analyse(path: Path, settings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = build_dependency_graph(extract_repository_ast(path, settings))
    return graph, create_node_features(graph)


def future_moment(merged_at: str, months: int) -> datetime:
    """End of the calendar month that is ``months`` after the merge (UTC)."""
    merged = datetime.fromisoformat(merged_at).astimezone(timezone.utc)
    target = add_calendar_months(merged, months)
    last_day = calendar.monthrange(target.year, target.month)[1]
    return target.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)


def future_summary(snapshots: Snapshotter, sha: str, cache_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    cached = cache_dir / f"{sha}.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    graph, _ = analyse(snapshots.checkout(sha), settings)
    summary = coupling_summary(graph)
    _write_json(cached, summary)
    return summary


def build_coupling_sample(repo: str, pr: MergedPR, snapshots: Snapshotter, output_root: Path,
                          cache_dir: Path, settings: dict[str, Any], *, horizon_months: int,
                          threshold: float) -> dict[str, Any]:
    excluded_dirs = set(settings["excluded_directory_names"])
    excluded_files = set(settings.get("excluded_file_names", []))
    files = production_python_files(changed_paths(snapshots.repository, pr.before_sha, pr.merge_sha),
                                    excluded_dirs, excluded_files)
    if not files:
        raise SampleSkipped("no production Python change")
    future_sha = commit_at_or_before(snapshots.repository, future_moment(pr.merged_at, horizon_months))
    if future_sha is None or future_sha == pr.merge_sha:
        raise SampleSkipped("no later snapshot for the outcome window")

    before_graph, before_features = analyse(snapshots.checkout(pr.before_sha), settings)
    after_graph, after_features = analyse(snapshots.checkout(pr.merge_sha), settings)
    at_merge = coupling_summary(after_graph)
    touched = touched_module_names(at_merge, files)
    if not touched:
        raise SampleSkipped("changed files are not analysed project modules")
    future = future_summary(snapshots, future_sha, cache_dir, settings)
    label = future_coupling_label(at_merge, future, touched, threshold)
    if label["label"] is None:
        raise SampleSkipped(label["reason"])
    label["pr_creates_cycle"] = create_cycle_label(before_graph, after_graph, files)["label"]
    label["future_commit_sha"] = future_sha

    sample_dir = output_root / repo.replace("/", "__") / str(pr.number)
    sample_dir.mkdir(parents=True, exist_ok=True)
    data = attach_touched_masks(build_hetero_data(after_graph, after_features), files)
    deltas = node_delta_features(before_graph, after_graph)
    for node_type in data.node_types:
        rows = [deltas[node_id] for node_id in data[node_type].node_ids]
        data[node_type].delta = torch.tensor(rows, dtype=torch.float32).reshape(len(rows), len(DELTA_FEATURE_NAMES))
    data.delta_feature_names = list(DELTA_FEATURE_NAMES)
    save_hetero_data(data, sample_dir / "graph.pt")
    diff = _git(snapshots.repository, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=3",
                pr.before_sha, pr.merge_sha, "--", *files)
    (sample_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
    _write_json(sample_dir / "metrics.json",
                compare_structural_metrics(before_graph, before_features, after_graph, after_features))
    _write_json(sample_dir / "label.json", label)
    metadata = {
        "schema_version": SCHEMA_VERSION, "label_protocol": "future_coupling_v1",
        "sample_id": f"{repo}#{pr.number}", "repo": repo, "pr_number": pr.number, "title": pr.title,
        "merged_at": pr.merged_at, "before_commit_sha": pr.before_sha, "merge_commit_sha": pr.merge_sha,
        "future_commit_sha": future_sha, "horizon_months": horizon_months,
        "changed_python_files": files, "touched_modules": touched,
        "graph_path": "graph.pt", "graph_state": "at_merge_with_pr_delta", "diff_path": "diff.patch",
        "label": label["label"], "label_reason": label["reason"], "excess_growth": label["excess_growth"],
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(sample_dir / "metadata.json", metadata)
    return metadata


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repository), *arguments], check=False, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout
