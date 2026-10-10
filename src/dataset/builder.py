"""Build one trainable pull-request sample by reusing analysis Steps 2-5 twice."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.analysis.pipeline import analyse_repository
from src.dataset.cycle_labels import create_cycle_label
from src.dataset.git_snapshots import (
    changed_python_files,
    detached_snapshot,
    resolve_commit_pair,
    write_python_diff,
)
from src.ml.hetero_data import build_hetero_data, save_hetero_data


class DatasetBuildError(RuntimeError):
    """A PR record is incomplete or its output location is unsafe to reuse."""


class DatasetSampleExcluded(RuntimeError):
    """A valid PR is unsuitable for this Python graph dataset."""


def build_pr_sample(pr: dict[str, Any], repository_path: str | Path,
                    output_root: str | Path, analysis_settings: dict[str, Any]) -> dict[str, Any]:
    """Create diff, BEFORE/AFTER analysis, HeteroData graphs, label and metadata."""
    repo_name = pr.get("repo")
    pr_number = pr.get("pr_number")
    merge_sha = pr.get("merge_commit_sha")
    if not isinstance(repo_name, str) or repo_name.count("/") != 1:
        raise DatasetBuildError(f"Invalid repository name: {repo_name!r}")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise DatasetBuildError(f"Invalid PR number: {pr_number!r}")
    if not isinstance(merge_sha, str):
        raise DatasetBuildError(f"PR {repo_name}#{pr_number} has no merge_commit_sha")

    pair = resolve_commit_pair(repository_path, merge_sha)
    sample_id = f"{repo_name}#{pr_number}"
    sample_dir = Path(output_root) / repo_name.replace("/", "__") / str(pr_number)
    if sample_dir.exists():
        raise DatasetBuildError(f"Sample output already exists: {sample_dir}")
    changed_paths = changed_python_files(repository_path, pair)
    if not changed_paths:
        raise DatasetSampleExcluded(f"PR {sample_id} changes no Python files")
    sample_dir.mkdir(parents=True)
    worktree_root = Path(output_root) / ".worktrees" / uuid4().hex
    write_python_diff(repository_path, pair, sample_dir / "diff.patch")

    results: dict[str, dict[str, Any]] = {}
    for state, sha in (("before", pair.before_sha), ("after", pair.after_sha)):
        with detached_snapshot(repository_path, sha, worktree_root / state) as snapshot:
            analysis = analyse_repository(snapshot, sample_dir / state, analysis_settings)
        data = build_hetero_data(analysis["graph"], analysis["features"])
        save_hetero_data(data, sample_dir / state / "graph.pt")
        results[state] = analysis

    label = create_cycle_label(results["before"]["graph"], results["after"]["graph"], changed_paths)
    _write_json(sample_dir / "label.json", label)
    metadata = {
        "schema_version": 1,
        "sample_id": sample_id,
        "repo": repo_name,
        "pr_number": pr_number,
        "merge_commit_sha": pair.after_sha,
        "before_commit_sha": pair.before_sha,
        "after_commit_sha": pair.after_sha,
        "changed_python_files": changed_paths,
        "diff_path": "diff.patch",
        "before_graph_path": "before/graph.pt",
        "after_graph_path": "after/graph.pt",
        "label_path": "label.json",
        "label": label["label"],
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(sample_dir / "metadata.json", metadata)
    return metadata


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
