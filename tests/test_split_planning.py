from src.ml.split_planning import chronological_cutoffs


def record(repo: str, number: int, date: str, label: int = 0) -> dict:
    return {"sample_id": f"{repo}#{number}", "merged_at": date, "label": label}


def test_cutoffs_are_chronological_and_do_not_depend_on_labels():
    rows = [record("org/repo", i, f"202{i}-01-01T00:00:00Z", i % 2) for i in range(6)]
    first = chronological_cutoffs(rows)
    second = chronological_cutoffs([{**row, "label": 1 - row["label"]} for row in rows])
    assert first == second
    assert first["org/repo"] == {
        "train_cutoff": "2024-01-01T00:00:00Z",
        "validation_cutoff": "2025-01-01T00:00:00Z",
    }


def test_cutoffs_require_ordered_fractions_and_enough_samples():
    import pytest

    with pytest.raises(ValueError, match="fraction"):
        chronological_cutoffs([], 0.8, 0.5)
    with pytest.raises(ValueError, match="at least three"):
        chronological_cutoffs([record("org/repo", 1, "2020-01-01T00:00:00Z")])
