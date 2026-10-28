"""Set-based precision / recall / F1 shared by every validation check."""
from __future__ import annotations

from typing import Any, Hashable, Iterable


def counts(predicted: Iterable[Hashable], gold: Iterable[Hashable]) -> dict[str, int]:
    predicted, gold = set(predicted), set(gold)
    return {"tp": len(predicted & gold), "fp": len(predicted - gold), "fn": len(gold - predicted)}


def scores(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """P = tp/(tp+fp), R = tp/(tp+fn), F1 = 2PR/(P+R); None where the denominator is 0."""
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else
          (0.0 if precision is not None and recall is not None else None))
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def micro(rows: Iterable[dict[str, int]]) -> dict[str, Any]:
    """Micro-average: add up tp/fp/fn over all rows, then score once."""
    total = {"tp": 0, "fp": 0, "fn": 0}
    for row in rows:
        for key in total:
            total[key] += row[key]
    return scores(**total)


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}"
