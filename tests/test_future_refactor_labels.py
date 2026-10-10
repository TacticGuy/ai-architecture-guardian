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


def test_labels_overlap_in_later_refactor_pr_as_positive():
    samples = [pr(1, "2024-01-10T00:00:00Z")]
    events = [pr(9, "2024-04-10T00:00:00Z")]
    files = {"org/repo#1": ["pkg/service.py"], "org/repo#9": ["pkg/service.py"]}

    labels = assign_future_refactor_labels(
        samples, events, files, {"org/repo": datetime(2024, 8, 1, tzinfo=timezone.utc)}
    )

    assert labels[0]["status"] == "labelled"
    assert labels[0]["label"] == 1
    assert labels[0]["triggering_refactor_pr"] == "org/repo#9"
    assert labels[0]["matched_python_files"] == ["pkg/service.py"]


def test_requires_full_six_month_follow_up_before_assigning_negative():
    sample = pr(1, "2024-01-10T00:00:00Z")
    files = {"org/repo#1": ["pkg/service.py"]}

    censored = assign_future_refactor_labels(
        [sample], [], files, {"org/repo": datetime(2024, 6, 30, tzinfo=timezone.utc)}
    )[0]
    negative = assign_future_refactor_labels(
        [sample], [], files, {"org/repo": datetime(2024, 7, 10, tzinfo=timezone.utc)}
    )[0]

    assert censored["status"] == "censored" and censored["label"] is None
    assert negative["status"] == "labelled" and negative["label"] == 0


def test_different_file_and_event_after_horizon_do_not_make_positive():
    sample = pr(1, "2024-01-10T00:00:00Z")
    events = [pr(2, "2024-02-10T00:00:00Z"), pr(3, "2024-08-01T00:00:00Z")]
    files = {
        "org/repo#1": ["pkg/service.py"],
        "org/repo#2": ["pkg/other.py"],
        "org/repo#3": ["pkg/service.py"],
    }
    result = assign_future_refactor_labels(
        [sample], events, files, {"org/repo": datetime(2024, 9, 1, tzinfo=timezone.utc)}
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


def test_only_explicit_pr_titles_become_future_refactor_events():
    records = [
        {"pr_id": "org/repo#1", "title": "Refactor service", "commit_messages": []},
        {"pr_id": "org/repo#2", "title": "Fix service", "commit_messages": ["refactor helper"]},
        {"pr_id": "org/repo#3", "title": "Decouple cache", "commit_messages": []},
    ]
    selected = explicit_refactor_events(records, ["refactor", "decouple"])
    assert [record["pr_id"] for record in selected] == ["org/repo#1", "org/repo#3"]
