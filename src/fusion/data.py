"""Load the GNN vectors and the CodeReviewer vectors and line them up by sample_id.

The manifest (``artifacts/gnn_embeddings_<version>.json``) is the single source of truth for
which samples exist and what their label and split are. Both embedding files must agree with
it exactly; any disagreement stops the run instead of being silently "fixed".
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import torch

SPLITS = ("train", "validation", "test")


class AlignmentError(ValueError):
    """The manifest and the embedding files disagree; nothing should be trained."""


@dataclass
class AlignedData:
    sample_ids: list[str]          # manifest order
    labels: torch.Tensor           # long [N]
    splits: list[str]              # "train" / "validation" / "test"
    gnn: torch.Tensor              # float64 [N, gnn_dim]
    diff: torch.Tensor             # float64 [N, diff_dim]
    sources: dict[str, Any]        # file names + sha256, recorded with the results

    def indices(self, split: str) -> list[int]:
        return [row for row, value in enumerate(self.splits) if value == split]


def manifest_version(manifest_path: Path) -> str | None:
    """'gnn_embeddings_v4.json' -> 'v4'; None when the name carries no version."""
    match = re.search(r"_(v\d+)$", Path(manifest_path).stem)
    return match.group(1) if match else None


def load_aligned(manifest_path: Path, gnn_path: Path, diff_path: Path) -> AlignedData:
    manifest_raw = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_raw)
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AlignmentError(f"{manifest_path} has no 'rows'")
    order = [row.get("sample_id") for row in rows]
    _require_unique(order, "manifest")
    expected = {row["sample_id"]: row for row in rows}
    for row in rows:
        if row.get("label") not in (0, 1) or row.get("split") not in SPLITS:
            raise AlignmentError(f"manifest: bad label/split for {row.get('sample_id')}")
    if isinstance(manifest.get("count"), int) and manifest["count"] != len(rows):
        raise AlignmentError(f"manifest says count={manifest['count']} but has {len(rows)} rows")

    gnn_store = torch.load(gnn_path, weights_only=True)
    diff_store = torch.load(diff_path, weights_only=True)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    built_for = (diff_store.get("manifest") or {}).get("sha256")
    if built_for is not None and built_for != manifest_sha:
        raise AlignmentError(f"{diff_path} was built for a different manifest. Rebuild it with "
                             f"build_diff_embeddings.py --manifest {Path(manifest_path).name}")

    gnn = _rows_in_order(gnn_store, "GNN embeddings", expected, order)
    diff = _rows_in_order(diff_store, "CodeReviewer embeddings", expected, order)
    splits = [expected[sample_id]["split"] for sample_id in order]
    missing = [split for split in SPLITS if split not in splits]
    if missing:
        raise AlignmentError(f"manifest has no {', '.join(missing)} samples")
    return AlignedData(
        sample_ids=order,
        labels=torch.tensor([expected[sample_id]["label"] for sample_id in order], dtype=torch.long),
        splits=splits, gnn=gnn, diff=diff,
        sources={"manifest": _describe(manifest_path, manifest_raw),
                 "gnn_embeddings": _describe(gnn_path), "diff_embeddings": _describe(diff_path),
                 "diff_model": diff_store.get("model_name"), "split_counts": dict(Counter(splits))})


def _rows_in_order(store: dict[str, Any], name: str, expected: dict[str, dict], order: list[str]) -> torch.Tensor:
    ids = list(store.get("sample_ids", []))
    embeddings = store.get("embeddings")
    if not isinstance(embeddings, torch.Tensor) or embeddings.dim() != 2 or embeddings.shape[0] != len(ids):
        raise AlignmentError(f"{name}: 'embeddings' must be a [N, dim] tensor matching 'sample_ids'")
    _require_unique(ids, name)
    if set(ids) != set(expected):
        raise AlignmentError(f"{name}: sample_ids differ from the manifest "
                             f"(missing {sorted(set(expected) - set(ids))}, extra {sorted(set(ids) - set(expected))})")
    labels = [int(value) for value in store["labels"]] if "labels" in store else None
    splits = list(store["splits"]) if store.get("splits") is not None else None
    for position, sample_id in enumerate(ids):
        if labels is not None and labels[position] != expected[sample_id]["label"]:
            raise AlignmentError(f"{name}: label of {sample_id} is {labels[position]}, "
                                 f"manifest says {expected[sample_id]['label']}")
        if splits is not None and splits[position] != expected[sample_id]["split"]:
            raise AlignmentError(f"{name}: split of {sample_id} is {splits[position]}, "
                                 f"manifest says {expected[sample_id]['split']}")
    position = {sample_id: index for index, sample_id in enumerate(ids)}
    matrix = embeddings[[position[sample_id] for sample_id in order]].double()
    if not bool(torch.isfinite(matrix).all()):
        raise AlignmentError(f"{name}: contains NaN or infinity")
    return matrix


def _require_unique(ids: list[Any], name: str) -> None:
    duplicates = sorted(str(value) for value, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise AlignmentError(f"{name}: duplicate sample_ids {duplicates}")


def _describe(path: Path, raw: bytes | None = None) -> dict[str, str]:
    data = raw if raw is not None else Path(path).read_bytes()
    return {"file": Path(path).name, "sha256": hashlib.sha256(data).hexdigest()}
