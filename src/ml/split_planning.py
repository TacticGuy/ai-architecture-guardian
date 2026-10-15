"""Label-blind planning for per-repository temporal evaluation splits."""
from __future__ import annotations

import math
from typing import Any

from src.dataset.future_refactor_labels import parse_timestamp
from src.ml.gnn_data import temporal_split_by_repository


def chronological_cutoffs(
    records: list[dict[str, Any]], train_fraction: float = 0.55,
    validation_fraction: float = 0.80,
) -> dict[str, dict[str, str]]:
    """Choose repository cutoffs from merge-time quantiles without reading labels."""
    if not 0 < train_fraction < validation_fraction < 1:
        raise ValueError("Need 0 < train fraction < validation fraction < 1")
    grouped: dict[str, list] = {}
    for record in records:
        sample_id = record.get("sample_id")
        merged = parse_timestamp(record.get("merged_at"))
        if not isinstance(sample_id, str) or "#" not in sample_id or merged is None:
            raise ValueError(f"Invalid sample metadata: {sample_id!r}")
        grouped.setdefault(sample_id.split("#", 1)[0], []).append(merged)
    result = {}
    for repo, dates in sorted(grouped.items()):
        dates.sort()
        if len(dates) < 3:
            raise ValueError(f"Need at least three dated samples for {repo}")
        train_index = min(len(dates) - 2, max(1, math.ceil(len(dates) * train_fraction)))
        validation_index = min(
            len(dates) - 1,
            max(train_index + 1, math.ceil(len(dates) * validation_fraction)),
        )
        result[repo] = {
            "train_cutoff": dates[train_index].isoformat().replace("+00:00", "Z"),
            "validation_cutoff": dates[validation_index].isoformat().replace("+00:00", "Z"),
        }
    return result


def split_report(records: list[dict[str, Any]], cutoffs: dict[str, dict[str, str]]) -> dict:
    """Report labels after fixed chronological cutoffs; never alter the cutoffs."""
    partitions = temporal_split_by_repository(records, cutoffs)
    result = {}
    for name, rows in partitions.items():
        by_repo = {}
        for row in rows:
            repo = row["sample_id"].split("#", 1)[0]
            counts = by_repo.setdefault(repo, {"safe": 0, "risky": 0, "total": 0})
            counts["safe" if int(row["label"]) == 0 else "risky"] += 1
            counts["total"] += 1
        result[name] = {
            "safe": sum(int(row["label"]) == 0 for row in rows),
            "risky": sum(int(row["label"]) == 1 for row in rows),
            "total": len(rows),
            "repositories": dict(sorted(by_repo.items())),
        }
    return result
