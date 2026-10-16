from __future__ import annotations

import subprocess

from tests.test_pr_dataset_builder import analysis_settings, repository_with_new_cycle

from src.dataset.future_builder import build_future_risk_sample
from src.ml.hetero_data import load_hetero_data


def test_builds_before_only_future_risk_sample_with_touched_mask(tmp_path):
    repository, merge_sha = repository_with_new_cycle(tmp_path)
    parents = subprocess.run(
        ["git", "-C", str(repository), "rev-list", "--parents", "-n", "1", merge_sha],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    metadata = build_future_risk_sample(
        {
            "repo": "example/project",
            "pr_number": 7,
            "merge_commit_sha": merge_sha,
            "head_ref_sha": parents[2],
            "commit_count": 1,
            "merged_at": "2024-01-01T00:00:00Z",
            "changed_python_files": ["pkg/b.py"],
            "label": 1,
            "label_type": "future_refactor_file_overlap",
            "label_protocol_version": 3,
            "causal_claim": False,
            "observation_start": "2023-01-01T00:00:00+00:00",
            "observation_end": "2025-01-01T00:00:00+00:00",
            "triggering_refactor_pr": "example/project#9",
            "event_evidence": {"references": ["fixture-diff"], "reviewer": "test"},
            "history_evidence": {"ancestry_verified": True, "file_identity": "unchanged_paths",
                                 "sample_after_sha": merge_sha, "history_validation_version": 1},
            "horizon_months": 6,
        },
        repository,
        tmp_path / "future-samples",
        analysis_settings(),
    )
    sample = tmp_path / "future-samples" / "example__project" / "7"
    graph = load_hetero_data(sample / "before" / "graph.pt")

    assert metadata["label"] == 1
    assert metadata["label_protocol_version"] == 3
    assert metadata["causal_claim"] is False
    assert metadata["triggering_refactor_pr"] == "example/project#9"
    assert metadata["event_evidence"]["references"] == ["fixture-diff"]
    assert (sample / "diff.patch").is_file()
    assert not (sample / "after").exists()
    module_ids = graph["module"].node_ids
    touched = graph["module"].touched_mask.tolist()
    assert dict(zip(module_ids, touched))["pkg/b.py:pkg.b"] is True
    assert dict(zip(module_ids, touched))["pkg/a.py:pkg.a"] is False
