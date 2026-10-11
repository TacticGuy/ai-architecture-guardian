from __future__ import annotations

import json

import pytest

from src.dataset.future_refactor_labels import add_calendar_months, parse_timestamp
from src.ml.gnn_data import discover_samples, temporal_split


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
