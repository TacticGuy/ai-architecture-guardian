from src.dataset.review_queue import blocker_ranked_review_queue


def test_queue_ranks_blockers_without_assigning_labels_or_decisions():
    audits = [
        {"sample_id": "org/repo#1", "unresolved_pr_ids": ["org/repo#8", "org/repo#9"]},
        {"sample_id": "org/repo#2", "unresolved_pr_ids": ["org/repo#8"]},
    ]
    evidence = [
        {"sample_id": "org/repo#8", "repo": "org/repo", "pr_number": 8,
         "after_sha": "a" * 40, "before_sha": "b" * 40, "merged_at": "2020-01-02T00:00:00Z",
         "title": "Large cleanup", "production_python_files": ["pkg/a.py"],
         "production_changes": [{"status": "M", "syntax": {"added_imports": ["import x"],
          "removed_imports": [], "added_declarations": [], "removed_declarations": []}}]},
        {"sample_id": "org/repo#9", "repo": "org/repo", "pr_number": 9,
         "after_sha": "c" * 40, "before_sha": "d" * 40, "merged_at": "2020-01-03T00:00:00Z",
         "title": "Refactor everything", "production_python_files": ["pkg/b.py"],
         "production_changes": []},
    ]
    queue = blocker_ranked_review_queue(audits, evidence)
    assert [item["sample_id"] for item in queue] == ["org/repo#8", "org/repo#9"]
    assert queue[0]["blocked_label_count"] == 2
    assert queue[0]["syntax_evidence_counts"]["added_imports"] == 1
    assert all("label" not in item and "decision" not in item for item in queue)


def test_queue_excludes_already_reviewed_ids():
    audits = [{"sample_id": "org/repo#1", "unresolved_pr_ids": ["org/repo#8"]}]
    evidence = [{"sample_id": "org/repo#8"}]
    assert blocker_ranked_review_queue(audits, evidence, {"org/repo#8"}) == []


def test_queue_excludes_provisional_history_diffs():
    audits = [{"sample_id": "org/repo#1", "unresolved_pr_ids": ["org/repo#8"]}]
    evidence = [{"sample_id": "org/repo#8", "diff_is_provisional": True}]
    assert blocker_ranked_review_queue(audits, evidence) == []
