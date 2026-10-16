"""Build one future-risk sample from the BEFORE graph and PR diff only."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from src.analysis.pipeline import analyse_repository
from src.dataset.builder import DatasetBuildError, DatasetSampleExcluded
from src.dataset.git_snapshots import (
    detached_snapshot, resolve_verified_commit_pair, write_python_diff,
)
from src.ml.gnn_data import attach_touched_masks
from src.ml.hetero_data import build_hetero_data, save_hetero_data


def build_future_risk_sample(
    label_record: dict[str, Any],
    repository_path: str | Path,
    output_root: str | Path,
    analysis_settings: dict[str, Any],
) -> dict[str, Any]:
    """Create the leakage-safe graph/diff input paired with a historical label."""
    repo_name = label_record.get("repo")
    pr_number = label_record.get("pr_number")
    merge_sha = label_record.get("merge_commit_sha")
    label = label_record.get("label")
    changed_paths = label_record.get("changed_python_files")
    if not isinstance(repo_name, str) or repo_name.count("/") != 1:
        raise DatasetBuildError(f"Invalid repository name: {repo_name!r}")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise DatasetBuildError(f"Invalid PR number: {pr_number!r}")
    if not isinstance(merge_sha, str):
        raise DatasetBuildError(f"PR {repo_name}#{pr_number} has no merge_commit_sha")
    if label not in (0, 1) or isinstance(label, bool):
        raise DatasetBuildError(f"PR {repo_name}#{pr_number} has invalid label {label!r}")
    if not isinstance(changed_paths, list) or not all(isinstance(path, str) for path in changed_paths):
        raise DatasetBuildError(f"PR {repo_name}#{pr_number} has invalid changed_python_files")
    if not changed_paths:
        raise DatasetSampleExcluded(f"PR {repo_name}#{pr_number} changes no analysed Python files")

    if label_record.get("label_protocol_version") != 3:
        raise DatasetBuildError("Future-risk graphs require corrected label protocol v3")
    pair = resolve_verified_commit_pair(repository_path, label_record)
    if label == 1 and not isinstance(label_record.get("history_evidence"), dict):
        raise DatasetBuildError("Positive label lacks verified commit/file-history evidence")
    if label == 1 and (
        label_record["history_evidence"].get("sample_after_sha") != pair.after_sha
        or label_record["history_evidence"].get("ancestry_verified") is not True
        or label_record["history_evidence"].get("file_identity") != "unchanged_paths"
    ):
        raise DatasetBuildError("Positive label history evidence does not match this PR")
    sample_id = f"{repo_name}#{pr_number}"
    output = Path(output_root)
    sample_dir = output / repo_name.replace("/", "__") / str(pr_number)
    if sample_dir.exists():
        raise DatasetBuildError(f"Sample output already exists: {sample_dir}")
    staging_root = output / ".staging" / uuid4().hex
    staging_dir = staging_root / "sample"
    staging_dir.mkdir(parents=True)
    try:
        write_python_diff(repository_path, pair, staging_dir / "diff.patch")
        worktree = output / ".worktrees" / uuid4().hex / "before"
        with detached_snapshot(repository_path, pair.before_sha, worktree) as snapshot:
            analysis = analyse_repository(snapshot, staging_dir / "before", analysis_settings)
        graph = attach_touched_masks(
            build_hetero_data(analysis["graph"], analysis["features"]), changed_paths
        )
        save_hetero_data(graph, staging_dir / "before" / "graph.pt")

        metadata = {
            "schema_version": 1,
            "sample_id": sample_id,
            "repo": repo_name,
            "pr_number": pr_number,
            "merged_at": label_record.get("merged_at"),
            "merge_commit_sha": pair.after_sha,
            "before_commit_sha": pair.before_sha,
            "head_ref_sha": label_record.get("head_ref_sha"),
            "commit_count": label_record.get("commit_count"),
            "changed_python_files": changed_paths,
            "diff_path": "diff.patch",
            "before_graph_path": "before/graph.pt",
            "label": label,
            "label_type": label_record.get("label_type"),
            "label_protocol_version": label_record.get("label_protocol_version"),
            "causal_claim": label_record.get("causal_claim", False),
            "horizon_months": label_record.get("horizon_months"),
            "horizon_end": label_record.get("horizon_end"),
            "observation_start": label_record.get("observation_start"),
            "observation_end": label_record.get("observation_end"),
            "triggering_refactor_pr": label_record.get("triggering_refactor_pr"),
            "triggering_refactor_merged_at": label_record.get("triggering_refactor_merged_at"),
            "matched_python_files": label_record.get("matched_python_files", []),
            "event_evidence": label_record.get("event_evidence"),
            "history_evidence": label_record.get("history_evidence"),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(staging_dir / "metadata.json", metadata)
        sample_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.replace(sample_dir)
        return metadata
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
