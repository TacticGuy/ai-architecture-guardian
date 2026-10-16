"""GNN-specific annotations layered onto the locked Step 5 HeteroData schema."""
from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

import torch
from torch_geometric.data import HeteroData

from src.dataset.future_refactor_labels import add_calendar_months, parse_timestamp


def discover_samples(root: str | Path) -> list[dict[str, Any]]:
    """Read prepared samples once, rejecting duplicate IDs and incomplete files."""
    records = []
    seen = set()
    for path in sorted(Path(root).glob("*/*/metadata.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        sample_id = record.get("sample_id")
        relative_graph = record.get("before_graph_path")
        if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
            raise ValueError(f"Missing or duplicate sample_id in {path}")
        if type(record.get("label")) is not int or record["label"] not in (0, 1):
            raise ValueError(f"Invalid binary label in {path}")
        if not isinstance(relative_graph, str) or not relative_graph:
            raise ValueError(f"Missing before_graph_path in {path}")
        graph_path = (path.parent / relative_graph).resolve()
        if not graph_path.is_relative_to(path.parent.resolve()) or not graph_path.is_file():
            raise ValueError(f"Missing or invalid graph path in {path}")
        record["_metadata_path"] = str(path)
        record["_graph_path"] = str(graph_path)
        records.append(record)
        seen.add(sample_id)
    return records


def temporal_split(records: list[dict[str, Any]], train_cutoff: str, validation_cutoff: str):
    """Separate samples by when their full future outcomes become observable.

    Training outcomes must be known by the first cutoff. Validation PRs start
    after that cutoff and their outcomes must be known by the second. Test PRs
    start after the second cutoff. The intervening incomplete horizons are purged.
    """
    first = parse_timestamp(train_cutoff)
    second = parse_timestamp(validation_cutoff)
    if first is None or second is None or first >= second:
        raise ValueError("Supply ordered, timezone-aware train and validation cutoffs")
    partitions = {"train": [], "validation": [], "test": [], "purged": []}
    ids = set()
    events = {}
    for record in records:
        sample_id = record["sample_id"]
        if sample_id in ids:
            raise ValueError(f"Duplicate sample_id: {sample_id}")
        ids.add(sample_id)
        merged = parse_timestamp(record.get("merged_at"))
        start = parse_timestamp(record.get("observation_start"))
        observed = parse_timestamp(record.get("observation_end"))
        horizon = parse_timestamp(record.get("horizon_end"))
        months = record.get("horizon_months")
        if (record.get("label_protocol_version") != 3 or merged is None or start is None
                or observed is None or horizon is None or type(months) is not int or months <= 0):
            raise ValueError(f"Missing verified outcome/coverage metadata for {sample_id}")
        if horizon != add_calendar_months(merged, months) or merged < start or horizon > observed:
            raise ValueError(f"Incomplete or inconsistent outcome window for {sample_id}")
        if horizon <= first:
            split_name = "train"
        elif merged >= first and horizon <= second:
            split_name = "validation"
        elif merged >= second:
            split_name = "test"
        else:
            split_name = "purged"
        if split_name != "purged" and record["label"] == 1:
            event_id = record.get("triggering_refactor_pr")
            event_time = parse_timestamp(record.get("triggering_refactor_merged_at"))
            if (not event_id or not record.get("event_evidence") or event_time is None
                    or not isinstance(record.get("history_evidence"), dict)
                    or record["history_evidence"].get("ancestry_verified") is not True
                    or record["history_evidence"].get("file_identity") != "unchanged_paths"
                    or record["history_evidence"].get("history_validation_version") != 1):
                raise ValueError(f"Missing positive event evidence for {sample_id}")
            if not merged < event_time <= horizon:
                raise ValueError(f"Positive event is outside the outcome window for {sample_id}")
            if event_id in events and events[event_id] != split_name:
                raise ValueError(f"Refactor event appears across splits: {event_id}")
            events[event_id] = split_name
        partitions[split_name].append(record)
    return partitions


def temporal_split_by_repository(
    records: list[dict[str, Any]], cutoffs: dict[str, dict[str, str]]
) -> dict[str, list[dict[str, Any]]]:
    """Apply independently chosen temporal cutoffs to each repository.

    Repositories mature at different times.  A single global date can therefore
    make repository identity a proxy for the split.  V4 uses this strict mapping
    so every included repository declares its own train and validation boundary.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        repo = _repository_id(record)
        grouped.setdefault(repo, []).append(record)
    missing = sorted(set(grouped) - set(cutoffs))
    extra = sorted(set(cutoffs) - set(grouped))
    if missing or extra:
        raise ValueError(f"Repository cutoff mismatch (missing={missing}, extra={extra})")
    combined = {name: [] for name in ("train", "validation", "test", "purged")}
    for repo in sorted(grouped):
        config = cutoffs[repo]
        if not isinstance(config, dict):
            raise ValueError(f"Cutoffs for {repo} must be a mapping")
        split = temporal_split(
            grouped[repo], config.get("train_cutoff", ""), config.get("validation_cutoff", "")
        )
        for name in combined:
            combined[name].extend(split[name])
    return combined


def repository_holdout_split(
    records: list[dict[str, Any]], config: dict[str, list[str]],
) -> dict[str, list[dict[str, Any]]]:
    """Split by disjoint repositories to measure unseen-project generalisation."""
    required = {"train", "validation", "test"}
    if set(config) != required:
        raise ValueError("Repository split config needs exactly train, validation and test")
    groups: dict[str, set[str]] = {}
    for name in sorted(required):
        values = config[name]
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and "/" in value for value in values
        ):
            raise ValueError(f"Repository split {name} must be a non-empty repository list")
        groups[name] = set(values)
    if any(groups[left] & groups[right] for left, right in (
        ("train", "validation"), ("train", "test"), ("validation", "test")
    )):
        raise ValueError("Repository split groups must be disjoint")
    available = {_repository_id(record) for record in records}
    configured = set().union(*groups.values())
    if available != configured:
        raise ValueError(
            f"Repository split mismatch (missing={sorted(available - configured)}, "
            f"extra={sorted(configured - available)})"
        )
    result = {name: [] for name in ("train", "validation", "test", "purged")}
    destination = {repo: name for name, repos in groups.items() for repo in repos}
    for record in records:
        result[destination[_repository_id(record)]].append(record)
    return result


def validate_training_cohort(
    partitions: dict[str, list[dict[str, Any]]], *, min_class_count: int,
    min_repositories: int,
) -> dict[str, Any]:
    """Reject cohorts that make all-risky or repository shortcuts too easy."""
    if min_class_count < 1 or min_repositories < 1:
        raise ValueError("Cohort minimums must be positive")
    report: dict[str, Any] = {"minimum_per_class": min_class_count,
                              "minimum_repositories": min_repositories, "splits": {}}
    all_repositories: set[str] = set()
    problems: list[str] = []
    for split_name in ("train", "validation", "test"):
        rows = partitions.get(split_name, [])
        repositories = {_repository_id(row) for row in rows}
        all_repositories.update(repositories)
        labels = {label: sum(int(row["label"]) == label for row in rows) for label in (0, 1)}
        by_repo: dict[str, dict[str, int]] = {}
        for repo in sorted(repositories):
            repo_rows = [row for row in rows if _repository_id(row) == repo]
            by_repo[repo] = {"safe": sum(int(row["label"]) == 0 for row in repo_rows),
                             "risky": sum(int(row["label"]) == 1 for row in repo_rows),
                             "total": len(repo_rows)}
        report["splits"][split_name] = {
            "total": len(rows), "safe": labels[0], "risky": labels[1],
            "repositories": by_repo,
        }
        for label, label_name in ((0, "safe"), (1, "risky")):
            if labels[label] < min_class_count:
                problems.append(
                    f"{split_name} has {labels[label]} {label_name} PRs; need at least {min_class_count}"
                )
    if len(all_repositories) < min_repositories:
        problems.append(
            f"cohort has {len(all_repositories)} repositories; need at least {min_repositories}"
        )
    report["repository_count"] = len(all_repositories)
    report["repositories"] = sorted(all_repositories)
    if problems:
        raise ValueError("; ".join(problems))
    return report


def _repository_id(record: dict[str, Any]) -> str:
    repo = record.get("repo")
    if isinstance(repo, str) and "/" in repo:
        return repo
    sample_id = record.get("sample_id")
    if isinstance(sample_id, str) and "#" in sample_id:
        return sample_id.split("#", 1)[0]
    raise ValueError(f"Cannot determine repository for {sample_id!r}")


def attach_touched_masks(data: HeteroData, changed_python_files: Iterable[str]) -> HeteroData:
    """Mark nodes defined in files touched by the PR, preserving all Step 5 features."""
    changed = {path.strip().replace("\\", "/") for path in changed_python_files if path.strip()}
    for node_type in data.node_types:
        node_ids = list(data[node_type].node_ids)
        data[node_type].touched_mask = torch.tensor(
            [_source_path(node_id) in changed for node_id in node_ids], dtype=torch.bool
        )
    return data


def _source_path(node_id: str) -> str:
    return node_id.split(":", 1)[0].replace("\\", "/")
