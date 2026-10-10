"""GNN-specific annotations layered onto the locked Step 5 HeteroData schema."""
from __future__ import annotations

from collections.abc import Iterable

import torch
from torch_geometric.data import HeteroData


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
