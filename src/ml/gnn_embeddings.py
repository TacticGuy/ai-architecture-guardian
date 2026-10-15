"""Export fixed GNN graph embeddings for the downstream fusion classifier."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import torch
from torch_geometric.loader import DataLoader

from src.ml.gnn_inference import load_gnn_checkpoint, load_gnn_model, prepare_graph
from src.ml.gnn_data import discover_samples


def export_gnn_embeddings(
    data_dir: str | Path,
    checkpoint_path: str | Path,
    output_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    device: str | torch.device | None = None,
    batch_size: int = 16,
    allow_smoke: bool = False,
) -> dict[str, Any]:
    """Export one stable pre-classifier embedding per prepared PR sample."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    data_root = Path(data_dir)
    records = discover_samples(data_root)
    if not records:
        raise ValueError(f"No complete GNN samples found under {data_root}")

    checkpoint = load_gnn_checkpoint(checkpoint_path)
    split_map, split_source = _resolve_splits(records, checkpoint, allow_smoke=allow_smoke)
    ordered = sorted(
        (record for record in records if record["sample_id"] in split_map),
        key=lambda record: record["sample_id"],
    )
    excluded_purged = len(records) - len(ordered)

    target_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = load_gnn_model(checkpoint, target_device)
    embedding_batches: list[torch.Tensor] = []
    with torch.no_grad():
        for offset in range(0, len(ordered), batch_size):
            graphs = [prepare_graph(record["_graph_path"], checkpoint)
                      for record in ordered[offset:offset + batch_size]]
            for batch in DataLoader(graphs, batch_size=batch_size, shuffle=False):
                embedding_batches.append(model.encode(batch.to(target_device)).cpu())
    embeddings = torch.cat(embedding_batches, dim=0).to(dtype=torch.float32).contiguous()
    pooling_mode = str(checkpoint.get("pooling_mode", "repo_plus_touched"))
    expected_dim = int(checkpoint["hidden_channels"]) * (2 if pooling_mode == "repo_plus_touched" else 1)
    if tuple(embeddings.shape) != (len(ordered), expected_dim):
        raise RuntimeError(
            f"Unexpected embedding shape {tuple(embeddings.shape)}; "
            f"expected {(len(ordered), expected_dim)}"
        )
    if not torch.isfinite(embeddings).all():
        raise RuntimeError("Exported embeddings contain NaN or infinite values")

    sample_ids = [record["sample_id"] for record in ordered]
    labels = torch.tensor([int(record["label"]) for record in ordered], dtype=torch.long)
    splits = [split_map[sample_id] for sample_id in sample_ids]
    bundle = {
        "schema_version": 1,
        "embedding_type": "gnn_pre_classifier",
        "embedding_dim": expected_dim,
        "sample_ids": sample_ids,
        "embeddings": embeddings,
        "labels": labels,
        "splits": splits,
        "split_source": split_source,
        "evaluation_status": checkpoint.get("results", {}).get("status", "unverified"),
        "checkpoint_name": Path(checkpoint_path).name,
        "threshold": float(checkpoint["threshold"]),
        "pooling_mode": pooling_mode,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_torch_save(bundle, output)

    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "schema_version": 1,
        "embedding_file": output.name,
        "embedding_type": bundle["embedding_type"],
        "embedding_dim": expected_dim,
        "count": len(ordered),
        "checkpoint_name": bundle["checkpoint_name"],
        "split_source": split_source,
        "evaluation_status": bundle["evaluation_status"],
        "pooling_mode": pooling_mode,
        "excluded_purged_count": excluded_purged,
        "rows": [
            {
                "row_index": index,
                "sample_id": sample_id,
                "label": int(labels[index]),
                "split": splits[index],
            }
            for index, sample_id in enumerate(sample_ids)
        ],
    }
    _atomic_text_save(json.dumps(manifest_payload, indent=2) + "\n", manifest)
    return {
        "output": str(output),
        "manifest": str(manifest),
        "count": len(ordered),
        "embedding_dim": expected_dim,
        "positive": int(labels.sum().item()),
        "negative": int((labels == 0).sum().item()),
        "excluded_purged": excluded_purged,
        "split_source": split_source,
        "device": str(target_device),
    }


def _resolve_splits(
    records: list[dict[str, Any]], checkpoint: dict[str, Any], *, allow_smoke: bool = False
) -> tuple[dict[str, str], str]:
    prepared_ids = {record["sample_id"] for record in records}
    saved = checkpoint.get("split_sample_ids")
    if saved is not None:
        if not isinstance(saved, dict):
            raise ValueError("Checkpoint split_sample_ids must be a mapping")
        split_map: dict[str, str] = {}
        all_checkpoint_ids: set[str] = set()
        for split_name in ("train", "validation", "test"):
            values = saved.get(split_name)
            if not isinstance(values, list):
                raise ValueError(f"Checkpoint is missing the {split_name!r} sample ID list")
            for sample_id in values:
                if sample_id in all_checkpoint_ids:
                    raise ValueError(f"Checkpoint assigns {sample_id!r} to multiple splits")
                all_checkpoint_ids.add(sample_id)
                split_map[sample_id] = split_name
        purged = saved.get("purged", [])
        if not isinstance(purged, list):
            raise ValueError("Checkpoint purged sample IDs must be a list")
        for sample_id in purged:
            if sample_id in all_checkpoint_ids:
                raise ValueError(f"Checkpoint assigns {sample_id!r} to multiple splits")
            all_checkpoint_ids.add(sample_id)
        if all_checkpoint_ids != prepared_ids:
            missing = sorted(prepared_ids - all_checkpoint_ids)
            extra = sorted(all_checkpoint_ids - prepared_ids)
            raise ValueError(
                "Checkpoint splits do not match the prepared dataset "
                f"(missing={missing[:3]}, extra={extra[:3]})"
            )
        return split_map, "checkpoint"

    if not allow_smoke:
        raise ValueError(
            "Checkpoint has no saved split_sample_ids. Split membership cannot be proven "
            "from its seed or sample count. Use --allow-smoke only for a development export."
        )
    return {sample_id: "unknown" for sample_id in prepared_ids}, "unknown_smoke_only"


def _atomic_torch_save(value: Any, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    torch.save(value, temporary)
    temporary.replace(destination)


def _atomic_text_save(value: str, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(destination)
