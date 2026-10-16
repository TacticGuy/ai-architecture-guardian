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
from src.ml.gnn_data import (
    discover_samples,
    temporal_split,
    temporal_split_by_repository,
    repository_holdout_split,
    validate_training_cohort,
)
from src.ml.shortcut_baselines import evaluate_shortcut_baselines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train a heterogeneous GNN future-risk classifier.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/future_pr_samples_v4")
    parser.add_argument("--output", type=Path, default=ROOT / "models/gnn_future_risk_v4.pt")
    parser.add_argument("--metrics", type=Path, default=ROOT / "data/statistics/gnn_metrics_v4.json")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--hidden-channels", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-cutoff", help="UTC timestamp when training outcomes must be known")
    parser.add_argument("--validation-cutoff", help="UTC timestamp when validation outcomes must be known")
    parser.add_argument(
        "--split-config", type=Path,
        help="JSON mapping each repository to its own train_cutoff and validation_cutoff (required for multi-repo)",
    )
    parser.add_argument(
        "--repository-split-config", type=Path,
        help="JSON with disjoint train/validation/test repository lists for unseen-repository evaluation",
    )
    parser.add_argument(
        "--pooling", choices=sorted(HeteroRiskGNN.POOLING_MODES), default="touched_1hop",
        help="Graph region pooled into the risk embedding (v4 default: touched_1hop)",
    )
    parser.add_argument("--min-class-count", type=int, default=20,
                        help="Minimum safe and risky samples required in every split")
    parser.add_argument("--min-repositories", type=int, default=3,
                        help="Minimum repositories required across the cohort")
    parser.add_argument(
        "--allow-smoke", action="store_true",
        help="Explicitly allow legacy unverified labels for software smoke tests only",
    )
    args = parser.parse_args(argv)
    if (args.epochs <= 0 or args.batch_size <= 0 or args.min_class_count <= 0
            or args.min_repositories <= 0):
        parser.error("epochs, batch size and cohort minimums must be positive")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    try:
        records = _discover(args.data_dir)
    except (OSError, ValueError) as error:
        print(f"Training blocked: {error}")
        return 2
    legacy = [record for record in records if record.get("label_protocol_version") != 3]
    if legacy and not args.allow_smoke:
        print(
            f"Training blocked: {len(legacy)} samples lack label protocol v3 history evidence. "
            "Build reviewed labels with verified collection coverage first. "
            "--allow-smoke is only for reproducing development runs."
        )
        return 2
    if len(records) < 10 or len({record["label"] for record in records}) < 2:
        print("Need at least 10 built graphs containing both labels.")
        return 2
    if args.allow_smoke:
        if (args.train_cutoff or args.validation_cutoff or args.split_config
                or args.repository_split_config):
            parser.error("Smoke mode uses its development split; omit temporal cutoffs and split config")
        train_records, validation_records, test_records = stratified_split(records, args.seed)
        split_name = "stratified_smoke"
        purged_records = []
        purged_count = 0
        cohort_report = None
    else:
        try:
            if args.split_config and args.repository_split_config:
                raise ValueError("Choose temporal --split-config or --repository-split-config, not both")
            if args.repository_split_config:
                repository_config = json.loads(
                    args.repository_split_config.read_text(encoding="utf-8")
                )
                if not isinstance(repository_config, dict):
                    raise ValueError("Repository split config must be a JSON object")
                splits = repository_holdout_split(records, repository_config)
                split_name = "repository_holdout"
            elif args.split_config:
                split_config = json.loads(args.split_config.read_text(encoding="utf-8"))
                if not isinstance(split_config, dict):
                    raise ValueError("Split config must be a JSON object keyed by owner/repository")
                splits = temporal_split_by_repository(records, split_config)
                split_name = "temporal_purged_per_repository"
            else:
                repositories = {record["sample_id"].split("#", 1)[0] for record in records}
                if len(repositories) > 1:
                    raise ValueError("Multi-repository training requires --split-config")
                if not args.train_cutoff or not args.validation_cutoff:
                    raise ValueError(
                        "Supply --train-cutoff and --validation-cutoff after inspecting cohort dates"
                    )
                splits = temporal_split(records, args.train_cutoff, args.validation_cutoff)
                split_name = "temporal_purged"
            cohort_report = validate_training_cohort(
                splits, min_class_count=args.min_class_count,
                min_repositories=args.min_repositories,
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            print(f"Training blocked: {error}")
            return 2
        train_records, validation_records, test_records = (
            splits[name] for name in ("train", "validation", "test")
        )
        purged_records = splits["purged"]
        purged_count = len(splits["purged"])
    for name, split_records in (
        ("train", train_records), ("validation", validation_records), ("test", test_records)
    ):
        if {record["label"] for record in split_records} != {0, 1}:
            print(f"Training blocked: {name} needs both outcome classes; collect more verified history.")
            return 2
    train_graphs = [_load(record) for record in train_records]
    validation_graphs = [_load(record) for record in validation_records]
    test_graphs = [_load(record) for record in test_records]
    try:
        shortcut_baselines = evaluate_shortcut_baselines(
            train_records, train_graphs, validation_records, validation_graphs,
            test_records, test_graphs,
        )
    except ValueError as error:
        print(f"Training blocked: shortcut baseline failure: {error}")
        return 2
    mean, std = _fit_scaler(train_graphs)
    for graph in train_graphs + validation_graphs + test_graphs:
        _scale(graph, mean, std)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HeteroRiskGNN(
        train_graphs[0].metadata(), len(TENSOR_FEATURE_NAMES), args.hidden_channels,
        pooling_mode=args.pooling,
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
    evaluation_status = (
        "repository_holdout_evaluation"
        if split_name == "repository_holdout"
        else "temporal_evaluation"
    )
    results = {
        "status": "smoke_evaluation_not_final" if args.allow_smoke else evaluation_status,
        "split": split_name,
        "pooling_mode": args.pooling,
        "purged_count": purged_count,
        "cohort": cohort_report,
        "score_type": "uncalibrated_sigmoid",
        "cutoffs": {"train": args.train_cutoff, "validation": args.validation_cutoff},
        "repository_split_config": (
            str(args.repository_split_config) if args.repository_split_config else None
        ),
        "device": str(device),
        "seed": args.seed,
        "train_count": len(train_graphs),
        "validation": binary_metrics(validation_labels, validation_probabilities, threshold),
        "test": binary_metrics(test_labels, test_probabilities, threshold),
        "shortcut_baselines": shortcut_baselines,
        "warning": "Compare baselines and inspect test uncertainty before claiming predictive value.",
    }
    best_shortcut_name, best_shortcut = max(
        shortcut_baselines.items(), key=lambda item: item[1]["test"]["pr_auc_average_precision"]
    )
    results["shortcut_check"] = {
        "best_baseline": best_shortcut_name,
        "best_baseline_test_pr_auc": best_shortcut["test"]["pr_auc_average_precision"],
        "gnn_test_pr_auc": results["test"]["pr_auc_average_precision"],
        "gnn_beats_best_baseline": (
            results["test"]["pr_auc_average_precision"]
            > best_shortcut["test"]["pr_auc_average_precision"]
        ),
    }
    if not args.allow_smoke and not results["shortcut_check"]["gnn_beats_best_baseline"]:
        results["status"] = "shortcut_check_failed"
        results["warning"] = (
            "The GNN did not beat the strongest shortcut baseline on the held-out test set. "
            "Do not present this checkpoint as validated predictive evidence."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "metadata": train_graphs[0].metadata(),
        "feature_names": list(TENSOR_FEATURE_NAMES),
        "feature_mean": mean.cpu(),
        "feature_std": std.cpu(),
        "hidden_channels": args.hidden_channels,
        "pooling_mode": args.pooling,
        "threshold": threshold,
        "seed": args.seed,
        "split_sample_ids": {
            "train": [record["sample_id"] for record in train_records],
            "validation": [record["sample_id"] for record in validation_records],
            "test": [record["sample_id"] for record in test_records],
            "purged": [record["sample_id"] for record in purged_records],
        },
        "results": results,
    }, args.output)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"Saved checkpoint: {args.output}")
    return 0


def _discover(root: Path) -> list[dict]:
    return discover_samples(root)


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
    if not probabilities:
        raise ValueError("Threshold selection requires validation predictions")
    candidates = sorted(set([0.5] + probabilities))
    def score(threshold):
        metrics = binary_metrics(labels, probabilities, threshold)
        return metrics["f1"], metrics["precision"], threshold
    return max(candidates, key=score)


if __name__ == "__main__":
    raise SystemExit(main())
