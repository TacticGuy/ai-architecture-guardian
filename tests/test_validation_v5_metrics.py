import pytest

from src.validation_v5.metrics import counts, micro, percent, scores


def test_counts_are_set_based():
    assert counts(["a", "b", "b", "c"], ["b", "c", "d"]) == {"tp": 2, "fp": 1, "fn": 1}


def test_scores_arithmetic():
    result = scores(tp=3, fp=1, fn=2)
    assert result["precision"] == pytest.approx(0.75)
    assert result["recall"] == pytest.approx(0.6)
    assert result["f1"] == pytest.approx(2 * 0.75 * 0.6 / 1.35)


def test_scores_with_empty_denominators():
    assert scores(0, 0, 4) == {"tp": 0, "fp": 0, "fn": 4, "precision": None, "recall": 0.0, "f1": None}
    assert scores(0, 2, 0)["recall"] is None
    assert scores(0, 2, 3)["f1"] == 0.0


def test_micro_average_adds_counts_before_scoring():
    # Macro would average 1.0 and 0.0; micro pools the counts: 1 / (1 + 3).
    rows = [{"tp": 1, "fp": 0, "fn": 0}, {"tp": 0, "fp": 3, "fn": 0}]
    assert micro(rows)["precision"] == pytest.approx(0.25)


def test_percent():
    assert percent(0.9724) == "97.2"
    assert percent(None) == "n/a"
