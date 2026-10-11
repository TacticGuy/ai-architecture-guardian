from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.label_future_refactors import main
from src.dataset.future_refactor_labels import assign_future_refactor_labels, parse_timestamp
from src.dataset.label_protocol import validate_coverage, validate_event_reviews
from tests.test_future_refactor_labels import pr, window


def coverage(ids: list[str], *, completed: bool = True) -> dict:
    return {"schema_version": 1, "repositories": [{
        "repo": "org/repo", "window_start": "2024-01-01T00:00:00Z",
        "window_end": "2024-12-31T23:59:59Z", "pagination_completed": completed,
        "source": "github_repository_pull_requests", "order": "CREATED_AT_ASC",
        "completion_reason": "connection_exhausted" if completed else None,
        "collected_pr_ids": ids,
    }]}


def review(source: dict, decision: str) -> dict:
    return {
        "sample_id": source["pr_id"], "merge_commit_sha": source["merge_commit_sha"],
        "decision": decision, "reviewer": "developer-a",
        "rationale": "Verified production dependency was removed in the source diff",
        "evidence_refs": ["https://example.test/pull/9/files"],
        "affected_python_files": ["pkg/service.py"],
    }


def test_coverage_checks_pagination_exact_ids_and_aware_timestamps():
    rows = [pr(1, "2024-01-10T00:00:00Z"), pr(9, "2024-04-10T00:00:00Z")]
    ids = [row["pr_id"] for row in rows]
    assert validate_coverage(coverage(ids), rows)["org/repo"][0].year == 2024
    with pytest.raises(ValueError, match="pagination is incomplete"):
        validate_coverage(coverage(ids, completed=False), rows)
    with pytest.raises(ValueError, match="do not match"):
        validate_coverage(coverage(ids[:-1]), rows)
    bad = coverage(ids)
    bad["repositories"][0]["window_start"] = "2024-01-01T00:00:00"
    with pytest.raises(ValueError, match="timezone"):
        validate_coverage(bad, rows)
    assert parse_timestamp("2024-01-01T00:00:00") is None


def test_keyword_title_without_review_is_unknown_not_an_architecture_event():
    source = {**pr(9, "2024-04-10T00:00:00Z"), "title": "Refactor architecture decouple"}
    files = {source["pr_id"]: ["pkg/service.py"]}
    accepted, unresolved = validate_event_reviews([], [source], files)
    assert accepted == []
    assert unresolved == [source]
    accepted, unresolved = validate_event_reviews(
        [review(source, "non_architectural")], [source], files
    )
    assert accepted == [] and unresolved == []


def test_review_can_validate_event_without_any_keyword_and_needs_matching_evidence():
    source = {**pr(9, "2024-04-10T00:00:00Z"), "title": "Change services"}
    files = {source["pr_id"]: ["pkg/service.py"]}
    approved = review(source, "architecture_refactor")
    accepted, unresolved = validate_event_reviews([approved], [source], files)
    assert len(accepted) == 1 and unresolved == []
    assert accepted[0]["reviewed_affected_files"] == ["pkg/service.py"]
    with pytest.raises(ValueError, match="commit does not match"):
        validate_event_reviews([{**approved, "merge_commit_sha": "different"}], [source], files)
    with pytest.raises(ValueError, match="evidence references"):
        validate_event_reviews([{**approved, "evidence_refs": []}], [source], files)
    with pytest.raises(ValueError, match="do not match Git changes"):
        validate_event_reviews(
            [{**approved, "affected_python_files": ["not_changed.py"]}], [source], files
        )


def test_review_resolution_changes_unknown_to_observed_outcome_without_claiming_causation():
    sample = pr(1, "2024-01-10T00:00:00Z")
    event = pr(9, "2024-04-10T00:00:00Z")
    files = {sample["pr_id"]: ["pkg/service.py"], event["pr_id"]: ["pkg/service.py"]}
    end = window(datetime(2024, 8, 1, tzinfo=timezone.utc))
    approved, unknown = validate_event_reviews([], [event], files)
    pair = {sample["pr_id"]: {event["pr_id"]: {
        "status": "verified", "matched_python_files": ["pkg/service.py"],
        "history_evidence": {"history_validation_version": 1, "ancestry_verified": True,
                             "same_target_history": True, "file_identity": "unchanged_paths"}}}}
    result = assign_future_refactor_labels(
        [sample], approved, files, end, unresolved_events=unknown, history_matches=pair,
    )[0]
    assert result["status"] == "unreviewed_outcome" and result["label"] is None
    for decision, expected in [("non_architectural", 0), ("architecture_refactor", 1)]:
        approved, unknown = validate_event_reviews([review(event, decision)], [event], files)
        result = assign_future_refactor_labels(
            [sample], approved, files, end, unresolved_events=unknown, history_matches=pair,
        )[0]
        assert result["label"] == expected
        assert result["causal_claim"] is False
        assert result["label_protocol_version"] == 3


def test_labels_require_verified_lineage_and_reject_unrelated_event_matches():
    sample = pr(1, "2024-01-10T00:00:00Z")
    event = pr(9, "2024-04-10T00:00:00Z")
    files = {sample["pr_id"]: ["pkg/service.py"], event["pr_id"]: ["pkg/service.py"]}
    end = window(datetime(2024, 8, 1, tzinfo=timezone.utc))
    approved, unresolved = validate_event_reviews([review(event, "architecture_refactor")], [event], files)
    unverified = assign_future_refactor_labels(
        [sample], approved, files, end, unresolved_events=unresolved,
    )[0]
    unrelated = assign_future_refactor_labels(
        [sample], approved, files, end, unresolved_events=unresolved,
        history_matches={sample["pr_id"]: {event["pr_id"]: {
            "status": "unrelated_lineage", "matched_python_files": ["pkg/service.py"],
            "history_evidence": {"history_validation_version": 1, "ancestry_verified": True,
                                 "same_target_history": False}}}},
    )[0]
    assert unverified["status"] == "unverified_lineage" and unverified["label"] is None
    assert unrelated["status"] == "labelled" and unrelated["label"] == 0


def test_unresolved_event_on_uncertain_file_history_blocks_negative():
    sample = pr(1, "2024-01-10T00:00:00Z")
    unknown = pr(9, "2024-04-10T00:00:00Z")
    files = {sample["pr_id"]: ["pkg/service.py"], unknown["pr_id"]: ["pkg/service.py"]}
    result = assign_future_refactor_labels(
        [sample], [], files, window(datetime(2024, 8, 1, tzinfo=timezone.utc)),
        unresolved_events=[unknown], history_matches={sample["pr_id"]: {
            unknown["pr_id"]: {"status": "uncertain_file_identity"}}},
    )[0]
    assert result["status"] == "unverified_followup_history" and result["label"] is None


def test_labeller_without_evidence_preserves_existing_outputs(tmp_path, capsys):
    output = tmp_path / "labels.jsonl"
    sentinel = json.dumps({"existing": True}) + "\n"
    output.write_text(sentinel, encoding="utf-8")
    assert main(["--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == sentinel
    assert "No outputs changed" in capsys.readouterr().out


def test_training_refuses_legacy_labels_before_loading_graphs(monkeypatch, capsys):
    from scripts import train_gnn

    monkeypatch.setattr(train_gnn, "_discover", lambda root: [
        {"sample_id": f"org/repo#{index}", "label": index % 2} for index in range(10)
    ])
    assert train_gnn.main(["--epochs", "1"]) == 2
    assert "lack label protocol v3 history evidence" in capsys.readouterr().out
