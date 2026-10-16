"""Point 5: convert a dependency graph and its node features into PyTorch Geometric ``HeteroData``.

The output keeps every node type and every edge type in its own "store" so a
heterogeneous GNN can learn separate rules for each. The schema is fixed: every graph
gets all node types and all edge types, even when some are empty, so graphs from
different repositories or commits can be batched together.

Values are stored raw (no scaling) and no reverse edges are added; both are training
decisions that belong to the GNN step.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from torch_geometric.data import HeteroData

SCHEMA_VERSION = 1

NODE_TYPES: tuple[str, ...] = ("module", "class", "function", "method", "external_module", "external_callable")

# Numeric columns of every node's ``x`` table, in this order. The ``node_type`` feature
# from node_features.json is dropped: the store a node sits in already says its type.
TENSOR_FEATURE_NAMES: tuple[str, ...] = (
    "loc", "parameter_count", "positional_parameter_count", "keyword_only_parameter_count",
    "has_vararg", "has_kwarg", "cyclomatic_complexity", "has_docstring", "is_async", "base_class_count",
    "in_degree", "out_degree", "import_out_degree", "call_out_degree", "contains_out_degree",
)

_SCOPES = ("module", "class", "function", "method")       # project nodes that can be an edge source
_CALL_TARGETS = ("module", "class", "function", "method", "external_callable")

# Every (source type, relation, target type) the static analysis can produce.
EDGE_TYPES: tuple[tuple[str, str, str], ...] = (
    # CONTAINS: what is defined inside what.
    ("module", "CONTAINS", "class"), ("module", "CONTAINS", "function"),
    ("class", "CONTAINS", "class"), ("class", "CONTAINS", "method"),
    ("function", "CONTAINS", "class"), ("function", "CONTAINS", "function"),
    ("method", "CONTAINS", "class"), ("method", "CONTAINS", "function"),
    # IMPORTS: any scope can import a project module or an outside module.
    *((source, "IMPORTS", target) for source in _SCOPES for target in ("module", "external_module")),
    # CALLS: any scope can call project code or something outside the project.
    *((source, "CALLS", target) for source in _SCOPES for target in _CALL_TARGETS),
    # INHERITS: a class's parents. Usually a class; other targets cover edge cases such
    # as ``class X(with_metaclass(Meta, Base))`` where the "parent" is a helper call.
    *(("class", "INHERITS", target) for target in _CALL_TARGETS),
)


def build_hetero_data(graph: dict[str, Any], features: dict[str, Any]) -> HeteroData:
    """Build a ``HeteroData`` object from ``dependency_graph.json`` and ``node_features.json`` contents.

    Each node type store has:
      * ``x``: float32 tensor ``[num_nodes, 15]`` with columns ``TENSOR_FEATURE_NAMES``
      * ``node_ids``: the original node IDs, in row order, to map results back to code
    Each edge type store has ``edge_index``: int64 tensor ``[2, num_edges]``.

    Raises ``ValueError`` for anything outside the fixed schema (unknown node or edge
    type, missing features, edges to unknown nodes) so schema drift is never silent.
    """
    feature_names = [name for name in features["summary"]["feature_names"] if name != "node_type"]
    if tuple(feature_names) != TENSOR_FEATURE_NAMES:
        raise ValueError(f"Unexpected node feature columns {feature_names}; expected {list(TENSOR_FEATURE_NAMES)}")
    features_by_id = {record["node_id"]: record["features"] for record in features["nodes"]}

    ids_by_type: dict[str, list[str]] = {node_type: [] for node_type in NODE_TYPES}
    position: dict[str, tuple[str, int]] = {}
    for node in graph["nodes"]:
        node_type = node["type"]
        if node_type not in ids_by_type:
            raise ValueError(f"Unknown node type {node_type!r} for node {node['id']}")
        if node["id"] not in features_by_id:
            raise ValueError(f"No features for node {node['id']}")
        position[node["id"]] = (node_type, len(ids_by_type[node_type]))
        ids_by_type[node_type].append(node["id"])

    data = HeteroData()
    for node_type, node_ids in ids_by_type.items():
        rows = [[float(features_by_id[node_id][name]) for name in TENSOR_FEATURE_NAMES] for node_id in node_ids]
        data[node_type].x = torch.tensor(rows, dtype=torch.float32).reshape(len(rows), len(TENSOR_FEATURE_NAMES))
        data[node_type].node_ids = node_ids

    pairs: dict[tuple[str, str, str], list[tuple[int, int]]] = {edge_type: [] for edge_type in EDGE_TYPES}
    for edge in graph["edges"]:
        if edge["source"] not in position or edge["target"] not in position:
            raise ValueError(f"Edge refers to an unknown node: {edge['source']} -> {edge['target']}")
        source_type, source_index = position[edge["source"]]
        target_type, target_index = position[edge["target"]]
        edge_type = (source_type, edge["type"], target_type)
        if edge_type not in pairs:
            raise ValueError(f"Edge type {edge_type} is not in the HeteroData schema")
        pairs[edge_type].append((source_index, target_index))

    for edge_type, edge_pairs in pairs.items():
        if edge_pairs:
            edge_index = torch.tensor(edge_pairs, dtype=torch.long).t().contiguous()
        else:
            edge_index = torch.empty((2, 0), dtype=torch.long)
        data[edge_type].edge_index = edge_index

    data.feature_names = list(TENSOR_FEATURE_NAMES)
    data.schema_version = SCHEMA_VERSION
    data.repository_path = graph.get("repository_path")
    return data


def save_hetero_data(data: HeteroData, path: str | Path) -> None:
    """Save atomically: a crash never leaves a half-written graph file behind."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    torch.save(data, temporary)
    temporary.replace(destination)


def load_hetero_data(path: str | Path) -> HeteroData:
    """Load a graph saved by ``save_hetero_data``.

    PyTorch 2.6+ refuses to unpickle custom objects such as ``HeteroData`` unless
    ``weights_only=False``. That setting runs pickle, so only load files this project
    created yourself, never ``.pt`` files from an untrusted source.
    """
    return torch.load(Path(path), weights_only=False)
