from datetime import datetime, timezone

from src.dataset.future_refactor_labels import (
    add_calendar_months,
    assign_future_refactor_labels,
    explicit_refactor_events,
    is_analysed_python_path,
    repository_observation_ends,
)


def pr(number: int, merged_at: str) -> dict:
    return {
        "pr_id": f"org/repo#{number}",
        "repo": "org/repo",
        "pr_number": number,
        "merged_at": merged_at,
        "merge_commit_sha": str(number) * 40,
    }


def window(end: datetime) -> dict:
    return {"org/repo": (datetime(2020, 1, 1, tzinfo=timezone.utc), end)}


def reviewed_event(number: int, merged_at: str, files: list[str]) -> dict:
    return {
        **pr(number, merged_at),
        "architecture_review_verified": True,
        "reviewed_affected_files": files,
        "event_evidence": {"reviewer": "developer", "rationale": "Removed a cross-layer dependency",
                           "references": ["https://example.test/review/9"]},
    }


def histories(sample_id: str, *matches: tuple[str, str, list[str]]):
    return {sample_id: {event_id: {"status": status, "matched_python_files": files,
                                   "history_evidence": {
                                       "history_validation_version": 1,
                                       "ancestry_verified": True,
                                       "same_target_history": status == "verified",
                                       **({"file_identity": "unchanged_paths"} if status == "verified" else {}),
                                   }}
                        for event_id, status, files in matches}}


def test_labels_overlap_in_later_refactor_pr_as_positive():
    samples = [pr(1, "2024-01-10T00:00:00Z")]
    events = [reviewed_event(9, "2024-04-10T00:00:00Z", ["pkg/service.py"])]
    files = {"org/repo#1": ["pkg/service.py"], "org/repo#9": ["pkg/service.py"]}

    labels = assign_future_refactor_labels(
        samples, events, files, window(datetime(2024, 8, 1, tzinfo=timezone.utc)),
        history_matches=histories("org/repo#1", ("org/repo#9", "verified", ["pkg/service.py"])),
    )

    assert labels[0]["status"] == "labelled"
    assert labels[0]["label"] == 1
    assert labels[0]["triggering_refactor_pr"] == "org/repo#9"
    assert labels[0]["matched_python_files"] == ["pkg/service.py"]


def test_requires_full_six_month_follow_up_before_assigning_negative():
    sample = pr(1, "2024-01-10T00:00:00Z")
    files = {"org/repo#1": ["pkg/service.py"]}

    censored = assign_future_refactor_labels(
        [sample], [], files, window(datetime(2024, 6, 30, tzinfo=timezone.utc)),
        history_matches=histories("org/repo#1"),
    )[0]
    negative = assign_future_refactor_labels(
        [sample], [], files, window(datetime(2024, 7, 10, tzinfo=timezone.utc)),
        history_matches=histories("org/repo#1"),
    )[0]

    assert censored["status"] == "censored" and censored["label"] is None
    assert negative["status"] == "labelled" and negative["label"] == 0


def test_different_file_and_event_after_horizon_do_not_make_positive():
    sample = pr(1, "2024-01-10T00:00:00Z")
    events = [reviewed_event(2, "2024-02-10T00:00:00Z", ["pkg/other.py"]),
              reviewed_event(3, "2024-08-01T00:00:00Z", ["pkg/service.py"])]
    files = {
        "org/repo#1": ["pkg/service.py"],
        "org/repo#2": ["pkg/other.py"],
        "org/repo#3": ["pkg/service.py"],
    }
    result = assign_future_refactor_labels(
        [sample], events, files, window(datetime(2024, 9, 1, tzinfo=timezone.utc)),
        history_matches=histories("org/repo#1", ("org/repo#2", "verified", [])),
    )[0]
    assert result["label"] == 0


def test_observation_end_is_repository_specific_and_calendar_months_clamp():
    records = [pr(1, "2024-01-01T00:00:00Z"), pr(2, "2024-03-01T00:00:00Z")]
    assert repository_observation_ends(records)["org/repo"] == datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert add_calendar_months(datetime(2024, 8, 31, tzinfo=timezone.utc), 6) == datetime(
        2025, 2, 28, tzinfo=timezone.utc
    )


def test_changed_paths_follow_the_locked_static_analysis_scope():
    settings = {
        "include_tests": False,
        "excluded_directory_names": ["docs"],
        "excluded_file_names": ["setup.py"],
    }
    assert is_analysed_python_path("src/pkg/service.py", settings)
    assert not is_analysed_python_path("tests/test_service.py", settings)
    assert not is_analysed_python_path("testing/test_service.py", settings)
    assert not is_analysed_python_path("docs/example.py", settings)
    assert not is_analysed_python_path("setup.py", settings)


def test_titles_only_discover_candidates_and_cannot_directly_assign_labels():
    records = [
        {"pr_id": "org/repo#1", "title": "Refactor service", "commit_messages": []},
        {"pr_id": "org/repo#2", "title": "Fix service", "commit_messages": ["refactor helper"]},
        {"pr_id": "org/repo#3", "title": "Decouple cache", "commit_messages": []},
    ]
    selected = explicit_refactor_events(records, ["refactor", "decouple"])
    assert [record["pr_id"] for record in selected] == ["org/repo#1", "org/repo#3"]
    import pytest
    with pytest.raises(ValueError, match="verified architectural review"):
        assign_future_refactor_labels([], selected, {}, {})


def test_early_positive_is_censored_until_full_horizon_is_observed():
    sample = pr(1, "2024-01-10T00:00:00Z")
    event = reviewed_event(9, "2024-04-10T00:00:00Z", ["pkg/service.py"])
    result = assign_future_refactor_labels(
        [sample], [event], {"org/repo#1": ["pkg/service.py"], "org/repo#9": ["pkg/service.py"]},
        window(datetime(2024, 5, 1, tzinfo=timezone.utc)),
        history_matches=histories("org/repo#1", ("org/repo#9", "verified", ["pkg/service.py"])),
    )[0]
    assert result["status"] == "censored" and result["label"] is None


def test_unverified_coverage_and_unknown_overlapping_outcomes_block_negatives():
    sample = pr(1, "2024-01-10T00:00:00Z")
    unknown = pr(9, "2024-04-10T00:00:00Z")
    files = {"org/repo#1": ["pkg/service.py"], "org/repo#9": ["pkg/service.py"]}
    missing = assign_future_refactor_labels(
        [sample], [], files, {}, history_matches=histories("org/repo#1"),
    )[0]
    unresolved = assign_future_refactor_labels(
        [sample], [], files, window(datetime(2024, 8, 1, tzinfo=timezone.utc)),
        unresolved_events=[unknown],
        history_matches=histories("org/repo#1", ("org/repo#9", "verified", ["pkg/service.py"])),
    )[0]
    assert missing["status"] == "unverified_coverage" and missing["label"] is None
    assert unresolved["status"] == "unreviewed_outcome" and unresolved["label"] is None


def test_sample_before_coverage_window_and_failed_file_extraction_are_not_negative():
    sample = pr(1, "2024-01-10T00:00:00Z")
    files = {"org/repo#1": ["pkg/service.py"]}
    outside = assign_future_refactor_labels(
        [sample], [], files, {"org/repo": (
            datetime(2024, 2, 1, tzinfo=timezone.utc), datetime(2024, 8, 1, tzinfo=timezone.utc))},
        history_matches=histories("org/repo#1"),
    )[0]
    failed = assign_future_refactor_labels(
        [sample], [], files, window(datetime(2024, 8, 1, tzinfo=timezone.utc)),
        samples_with_extraction_errors=["org/repo#1"], history_matches=histories("org/repo#1"),
    )[0]
    assert outside["status"] == "censored"
    assert failed["status"] == "incomplete_sample_history" and failed["label"] is None
