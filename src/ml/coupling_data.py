"""Load v5 future-coupling samples for the GNN: the PR's neighbourhood, with its own changes marked.

Each sample's ``graph.pt`` is the whole repository at merge time. The model only pools the
touched files and their direct neighbours after two message-passing layers, so nothing more than
three hops from a touched node can influence the score. Cutting the graph to that 3-hop
neighbourhood therefore changes no prediction, and makes training many times faster.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
from typing import Any

import torch
from torch_geometric.data import HeteroData

from src.dataset.history_features import HISTORY_FEATURE_NAMES
from src.ml.hetero_data import TENSOR_FEATURE_NAMES, load_hetero_data

DELTA_FEATURE_NAMES = ("is_new_in_pr", "dependency_edges_gained", "dependency_edges_lost")
INPUT_FEATURE_NAMES = (*TENSOR_FEATURE_NAMES, *DELTA_FEATURE_NAMES)


def discover_coupling_samples(root: str | Path) -> list[dict[str, Any]]:
    records, seen = [], set()
    for path in sorted(Path(root).glob("*/*/metadata.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("label_protocol") != "future_coupling_v1" or record.get("label") not in (0, 1):
            raise ValueError(f"Not a labelled v5 sample: {path}")
        if record["sample_id"] in seen:
            raise ValueError(f"Duplicate sample {record['sample_id']}")
        seen.add(record["sample_id"])
        record["_dir"] = str(path.parent)
        records.append(record)
    return records


def repository_split(records: list[dict[str, Any]], validation_fraction: float = 0.15,
                     test_fraction: float = 0.2, seed: int = 7) -> dict[str, list[str]]:
    """Assign whole repositories to train/validation/test (no project appears in two splits).

    Repositories are shuffled with a fixed seed, then test and validation are filled until
    they hold about the requested share of samples; the rest is training.
    """
    counts: dict[str, int] = {}
    for record in records:
        counts[record["repo"]] = counts.get(record["repo"], 0) + 1
    order = sorted(counts, key=lambda repo: hashlib.sha256(f"{seed}:{repo}".encode()).hexdigest())
    total = sum(counts.values())
    split = {"test": [], "validation": [], "train": []}
    filled = {"test": 0, "validation": 0}
    for repo in order:
        if filled["test"] < test_fraction * total:
            name = "test"
        elif filled["validation"] < validation_fraction * total:
            name = "validation"
        else:
            name = "train"
        split[name].append(repo)
        if name in filled:
            filled[name] += counts[repo]
    return {name: sorted(repos) for name, repos in split.items()}


def neighbourhood_masks(data: HeteroData, seeds: dict[str, torch.Tensor], hops: int) -> dict[str, torch.Tensor]:
    """Nodes within ``hops`` edges (either direction) of a seed node."""
    selected = {node_type: mask.clone() for node_type, mask in seeds.items()}
    for _ in range(hops):
        frontier = {node_type: mask.clone() for node_type, mask in selected.items()}
        for (source_type, _, target_type), edge_index in data.edge_index_dict.items():
            if edge_index.numel() == 0:
                continue
            sources, targets = edge_index
            frontier[target_type][targets[selected[source_type][sources]]] = True
            frontier[source_type][sources[selected[target_type][targets]]] = True
        selected = frontier
    return selected


def load_coupling_graph(record: dict[str, Any], hops: int = 3) -> HeteroData:
    """The sample's 3-hop neighbourhood of touched nodes, with ``x`` = 15 static + 3 PR-change features."""
    data = load_hetero_data(Path(record["_dir"]) / record.get("graph_path", "graph.pt"))
    keep = neighbourhood_masks(data, {nt: data[nt].touched_mask for nt in data.node_types}, hops)
    node_ids = {nt: list(data[nt].node_ids) for nt in data.node_types}
    for node_type in data.node_types:
        del data[node_type].node_ids
    subset = {nt: torch.nonzero(keep[nt]).view(-1) for nt in data.node_types}
    sub = data.subgraph(subset)
    for node_type in sub.node_types:
        store = sub[node_type]
        store.x = torch.cat([store.x, store.delta], dim=1)
        del store.delta
        store.node_ids = [node_ids[node_type][int(index)] for index in subset[node_type]]
    history = Path(record["_dir"]) / "history.json"
    if history.is_file():                      # v5.1 pre-merge history features (graph level)
        values = json.loads(history.read_text(encoding="utf-8"))["features"]
        sub.hist = torch.tensor([[float(values[name]) for name in HISTORY_FEATURE_NAMES]], dtype=torch.float32)
    sub.y = torch.tensor([float(record["label"])], dtype=torch.float32)
    sub.sample_id = record["sample_id"]
    return sub


def fit_scaler(graphs: list[HeteroData]) -> tuple[torch.Tensor, torch.Tensor]:
    rows = [torch.log1p(graph[nt].x) for graph in graphs for nt in graph.node_types if graph[nt].x.shape[0]]
    matrix = torch.cat(rows, dim=0)
    return matrix.mean(dim=0), matrix.std(dim=0, unbiased=False).clamp_min(1e-6)


def apply_scaler(graph: HeteroData, mean: torch.Tensor, std: torch.Tensor) -> HeteroData:
    for node_type in graph.node_types:
        graph[node_type].x = (torch.log1p(graph[node_type].x) - mean) / std
    return graph


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


def pack_graphs(records: list[dict[str, Any]], path: str | Path, hops: int = 3) -> int:
    """Save every sample's model input (the 3-hop subgraph, unscaled) in one file, without node
    ids, so training can run on another machine (e.g. a Kaggle GPU) without the raw dataset."""
    graphs = []
    for record in records:
        graph = load_coupling_graph(record, hops=hops)
        for node_type in graph.node_types:
            del graph[node_type].node_ids
        graphs.append(graph)
    torch.save({"format": "coupling_v5_packed/1", "input_features": list(INPUT_FEATURE_NAMES), "hops": hops,
                "graphs": graphs}, Path(path))
    return len(graphs)


def load_packed_graphs(path: str | Path) -> list[HeteroData]:
    payload = torch.load(Path(path), map_location="cpu", weights_only=False)
    if payload.get("format") != "coupling_v5_packed/1" or list(payload["input_features"]) != list(INPUT_FEATURE_NAMES):
        raise ValueError(f"{path} is not a packed v5 graph file for the current feature set")
    return payload["graphs"]


def fit_history_scaler(graphs: list[HeteroData]) -> tuple[torch.Tensor, torch.Tensor]:
    matrix = torch.cat([graph.hist for graph in graphs], dim=0)
    return matrix.mean(dim=0), matrix.std(dim=0, unbiased=False).clamp_min(1e-6)


def apply_history_scaler(graph: HeteroData, mean: torch.Tensor, std: torch.Tensor) -> HeteroData:
    graph.hist = (graph.hist - mean) / std
    return graph
