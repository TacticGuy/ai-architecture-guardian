from __future__ import annotations
from src.filtering.pipeline import FilterStatistics, filter_records


def test_pipeline_runs_impact_before_semantic_and_keeps_expected_records():
    records = iter([
        {"pr_id": "a#1", "changed_files": 2, "title": "refactor", "body": "", "commit_messages": []},
        {"pr_id": "a#2", "changed_files": 3, "title": "fix tests", "body": "", "commit_messages": []},
        {"pr_id": "a#3", "changed_files": 4, "title": "Refactor architecture", "body": "", "commit_messages": []},
    ])
    stats = FilterStatistics()
    accepted = list(filter_records(records, 3, ["refactor", "architecture"], stats))
    assert [pr["pr_id"] for pr in accepted] == ["a#3"]
    assert accepted[0]["matched_keywords"] == ["refactor", "architecture"]
    assert (stats.impact_rejected, stats.semantic_rejected, stats.final_accepted) == (1, 1, 1)


def test_pipeline_rejects_bot_release_notes_before_keyword_matching():
    records = iter([{
        "pr_id": "a#4",
        "author": "dependabot",
        "changed_files": 8,
        "title": "Bump dependency",
        "body": "<details>Major architecture rewrite</details>",
        "commit_messages": [],
    }])
    stats = FilterStatistics()
    assert list(filter_records(records, 3, ["architecture"], stats)) == []
    assert stats.automation_rejected == 1
    assert stats.impact_passed == 0
    assert stats.semantic_passed == 0

