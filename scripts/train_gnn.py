"""Train the future architecture-risk GNN on prepared BEFORE graphs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch
from torch_geometric.loader import DataLoader

from src.ml.hetero_data import TENSOR_FEATURE_NAMES, load_hetero_data
from src.ml.hetero_gnn import HeteroRiskGNN, binary_metrics, stratified_split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train a heterogeneous GNN future-risk classifier.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/future_pr_samples")
    parser.add_argument("--output", type=Path, default=ROOT / "models/gnn_future_risk.pt")
    parser.add_argument("--metrics", type=Path, default=ROOT / "data/statistics/gnn_metrics.json")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--hidden-channels", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.epochs <= 0 or args.batch_size <= 0:
        parser.error("epochs and batch size must be positive")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    records = _discover(args.data_dir)
    if len(records) < 10 or len({record["label"] for record in records}) < 2:
        print("Need at least 10 built graphs containing both labels.")
        return 2
    train_records, validation_records, test_records = stratified_split(records, args.seed)
    train_graphs = [_load(record) for record in train_records]
    validation_graphs = [_load(record) for record in validation_records]
    test_graphs = [_load(record) for record in test_records]
    mean, std = _fit_scaler(train_graphs)
    for graph in train_graphs + validation_graphs + test_graphs:
        _scale(graph, mean, std)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HeteroRiskGNN(
        train_graphs[0].metadata(), len(TENSOR_FEATURE_NAMES), args.hidden_channels
    ).to(device)
    positives = sum(int(graph.y.item()) for graph in train_graphs)
    negatives = len(train_graphs) - positives
    criterion = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negatives / max(positives, 1)], device=device)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    train_loader = DataLoader(train_graphs, batch_size=args.batch_size, shuffle=True)
    validation_loader = DataLoader(validation_graphs, batch_size=args.batch_size)
    test_loader = DataLoader(test_graphs, batch_size=args.batch_size)

    best_state = copy.deepcopy(model.state_dict())
    best_validation_loss = float("inf")
    stale_epochs = 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for batch in train_loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch), batch.y.float().view(-1))
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * int(batch.num_graphs)
        validation_loss, _, _ = _evaluate(model, validation_loader, criterion, device)
        print(f"epoch={epoch:03d} train_loss={train_loss / len(train_graphs):.4f} "
              f"validation_loss={validation_loss:.4f}")
        if validation_loss < best_validation_loss - 1e-5:
            best_validation_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= 8:
                break

    model.load_state_dict(best_state)
    _, validation_labels, validation_probabilities = _evaluate(model, validation_loader, criterion, device)
    _, test_labels, test_probabilities = _evaluate(model, test_loader, criterion, device)
    threshold = _best_f1_threshold(validation_labels, validation_probabilities)
    results = {
        "status": "smoke_evaluation_not_final",
        "split": "stratified",
        "device": str(device),
        "seed": args.seed,
        "train_count": len(train_graphs),
        "validation": binary_metrics(validation_labels, validation_probabilities, threshold),
        "test": binary_metrics(test_labels, test_probabilities, threshold),
        "warning": "Use a broader time-based split before reporting final research results.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "metadata": train_graphs[0].metadata(),
        "feature_names": list(TENSOR_FEATURE_NAMES),
        "feature_mean": mean.cpu(),
        "feature_std": std.cpu(),
        "hidden_channels": args.hidden_channels,
        "threshold": threshold,
        "results": results,
    }, args.output)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"Saved checkpoint: {args.output}")
    return 0


def _discover(root: Path) -> list[dict]:
    records = []
    for path in root.glob("*/*/metadata.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        graph_path = path.parent / record.get("before_graph_path", "")
        if record.get("label") in (0, 1) and graph_path.is_file():
            record["_metadata_path"] = str(path)
            records.append(record)
    return records


def _load(record: dict):
    metadata_path = Path(record["_metadata_path"])
    graph = load_hetero_data(metadata_path.parent / record["before_graph_path"])
    graph.y = torch.tensor([float(record["label"])], dtype=torch.float32)
    return graph


def _fit_scaler(graphs) -> tuple[torch.Tensor, torch.Tensor]:
    rows = [torch.log1p(graph[node_type].x) for graph in graphs for node_type in graph.node_types
            if graph[node_type].x.shape[0] > 0]
    matrix = torch.cat(rows, dim=0)
    mean = matrix.mean(dim=0)
    std = matrix.std(dim=0, unbiased=False).clamp_min(1e-6)
    return mean, std


def _scale(graph, mean: torch.Tensor, std: torch.Tensor) -> None:
    for node_type in graph.node_types:
        graph[node_type].x = (torch.log1p(graph[node_type].x) - mean) / std


def _evaluate(model, loader, criterion, device):
    model.eval()
    loss_sum = 0.0
    labels: list[int] = []
    probabilities: list[float] = []
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            logits = model(batch)
            targets = batch.y.float().view(-1)
            loss_sum += float(criterion(logits, targets).item()) * int(batch.num_graphs)
            labels.extend(int(value) for value in targets.cpu().tolist())
            probabilities.extend(float(value) for value in torch.sigmoid(logits).cpu().tolist())
    return loss_sum / max(len(labels), 1), labels, probabilities


def _best_f1_threshold(labels: list[int], probabilities: list[float]) -> float:
    candidates = sorted(set([0.5] + probabilities))
    return max(candidates, key=lambda threshold: binary_metrics(labels, probabilities, threshold)["f1"])


if __name__ == "__main__":
    raise SystemExit(main())
