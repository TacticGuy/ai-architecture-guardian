from __future__ import annotations

import json

import pytest

from src.dataset.future_refactor_labels import add_calendar_months, parse_timestamp
from src.ml.gnn_data import (
    discover_samples,
    temporal_split,
    temporal_split_by_repository,
    repository_holdout_split,
    validate_training_cohort,
)


def record(identifier: str, date: str, label: int = 0) -> dict:
    merged = parse_timestamp(date)
    result = {
        "sample_id": identifier, "label": label, "label_protocol_version": 3,
        "merged_at": date, "horizon_months": 6,
        "horizon_end": add_calendar_months(merged, 6).isoformat(),
        "observation_start": "2020-01-01T00:00:00Z",
        "observation_end": "2025-01-01T00:00:00Z",
    }
    if label:
        result.update({
            "triggering_refactor_pr": identifier + "-event",
            "triggering_refactor_merged_at": add_calendar_months(merged, 3).isoformat(),
            "event_evidence": {"references": ["fixture-diff"]},
            "history_evidence": {"ancestry_verified": True, "file_identity": "unchanged_paths",
                                 "history_validation_version": 1},
        })
    return result


def test_temporal_split_purges_unknown_future_at_each_cutoff():
    rows = [
        record("train", "2021-01-01T00:00:00Z", 1),
        record("first-gap", "2021-10-01T00:00:00Z"),
        record("validation", "2022-02-01T00:00:00Z", 1),
        record("second-gap", "2022-10-01T00:00:00Z"),
        record("test", "2023-02-01T00:00:00Z", 1),
    ]
    result = temporal_split(rows, "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z")
    assert [r["sample_id"] for r in result["train"]] == ["train"]
    assert [r["sample_id"] for r in result["validation"]] == ["validation"]
    assert [r["sample_id"] for r in result["test"]] == ["test"]
    assert [r["sample_id"] for r in result["purged"]] == ["first-gap", "second-gap"]


def test_temporal_split_rejects_reused_event_ids_and_censored_records():
    train = record("train", "2021-01-01T00:00:00Z", 1)
    validation = record("validation", "2022-02-01T00:00:00Z", 1)
    validation["triggering_refactor_pr"] = train["triggering_refactor_pr"]
    with pytest.raises(ValueError, match="across splits"):
        temporal_split([train, validation], "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z")
    censored = record("recent", "2024-10-01T00:00:00Z")
    with pytest.raises(ValueError, match="Incomplete"):
        temporal_split([censored], "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z")


def test_temporal_split_uses_independent_repository_cutoffs():
    first = record("org/old#1", "2021-01-01T00:00:00Z")
    second = record("org/new#1", "2021-01-01T00:00:00Z")
    result = temporal_split_by_repository([first, second], {
        "org/old": {"train_cutoff": "2022-01-01T00:00:00Z",
                    "validation_cutoff": "2023-01-01T00:00:00Z"},
        "org/new": {"train_cutoff": "2020-01-01T00:00:00Z",
                    "validation_cutoff": "2020-06-01T00:00:00Z"},
    })
    assert [row["sample_id"] for row in result["train"]] == ["org/old#1"]
    assert [row["sample_id"] for row in result["test"]] == ["org/new#1"]


def test_per_repository_split_requires_exact_cutoff_coverage():
    with pytest.raises(ValueError, match="cutoff mismatch"):
        temporal_split_by_repository(
            [record("org/repo#1", "2021-01-01T00:00:00Z")],
            {"wrong/repo": {"train_cutoff": "2022-01-01T00:00:00Z",
                            "validation_cutoff": "2023-01-01T00:00:00Z"}},
        )


def test_repository_holdout_is_disjoint_and_requires_exact_coverage():
    rows = [
        {"sample_id": "org/train#1", "label": 0},
        {"sample_id": "org/val#2", "label": 1},
        {"sample_id": "org/test#3", "label": 0},
    ]
    split = repository_holdout_split(rows, {
        "train": ["org/train"], "validation": ["org/val"], "test": ["org/test"],
    })
    assert [row["sample_id"] for row in split["train"]] == ["org/train#1"]
    assert [row["sample_id"] for row in split["validation"]] == ["org/val#2"]
    assert [row["sample_id"] for row in split["test"]] == ["org/test#3"]
    assert split["purged"] == []
    with pytest.raises(ValueError, match="disjoint"):
        repository_holdout_split(rows, {
            "train": ["org/train"], "validation": ["org/train"], "test": ["org/test"],
        })
    with pytest.raises(ValueError, match="mismatch"):
        repository_holdout_split(rows, {
            "train": ["org/train"], "validation": ["org/val"], "test": ["org/missing"],
        })


def test_cohort_gate_requires_both_classes_in_every_split_and_multiple_repositories():
    partitions = {name: [
        {"sample_id": f"org/a#{name}-safe", "label": 0},
        {"sample_id": f"org/a#{name}-risky", "label": 1},
        {"sample_id": f"org/b#{name}-safe", "label": 0},
        {"sample_id": f"org/b#{name}-risky", "label": 1},
    ] for name in ("train", "validation", "test")}
    partitions["purged"] = []
    report = validate_training_cohort(partitions, min_class_count=2, min_repositories=2)
    assert report["repository_count"] == 2
    assert report["splits"]["test"]["safe"] == 2
    with pytest.raises(ValueError, match="test has 1 safe"):
        validate_training_cohort(
            {**partitions, "test": partitions["test"][1:]},
            min_class_count=2, min_repositories=2,
        )


def test_discovery_rejects_duplicate_ids_and_missing_graphs(tmp_path):
    for number in (1, 2):
        folder = tmp_path / "repo" / str(number)
        folder.mkdir(parents=True)
        (folder / "graph.pt").touch()
        (folder / "metadata.json").write_text(json.dumps({
            "sample_id": "org/repo#1", "label": 1, "before_graph_path": "graph.pt",
        }), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate sample_id"):
        discover_samples(tmp_path)
    (tmp_path / "repo" / "1" / "graph.pt").unlink()
    with pytest.raises(ValueError, match="graph path"):
        discover_samples(tmp_path)
