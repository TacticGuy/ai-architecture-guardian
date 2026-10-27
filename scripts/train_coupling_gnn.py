"""Train the heterogeneous GNN on the v5 future-coupling dataset (several seeds, repository holdout).

    python scripts/train_coupling_gnn.py --data-dir data/coupling_samples_v5 --seeds 1 2 3 4 5

Whole repositories are held out (``config/coupling_split_v5.json`` is written on the first run
and reused afterwards, so every model in the project is tested on exactly the same PRs). The
threshold is the best-F1 threshold on validation. For each seed the script saves a checkpoint,
every sample's GNN embedding and score (for fusion and explanations), and the metrics.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
from torch_geometric.loader import DataLoader  # noqa: E402

from src.ml.coupling_data import (  # noqa: E402
    HISTORY_FEATURE_NAMES, INPUT_FEATURE_NAMES, apply_history_scaler, apply_scaler, discover_coupling_samples,
    fit_history_scaler, fit_scaler, load_coupling_graph, load_packed_graphs, repository_split, seed_everything,
)
from src.ml.hetero_gnn import HeteroRiskGNN, binary_metrics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/coupling_samples_v5")
    parser.add_argument("--graphs", type=Path, default=None,
                        help="packed graphs from pack_v5_graphs.py (use instead of --data-dir, e.g. on Kaggle)")
    parser.add_argument("--split", type=Path, default=ROOT / "config/coupling_split_v5.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/gnn_v5")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden-channels", type=int, default=64)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=0.002)
    parser.add_argument("--pooling", default="touched_1hop", choices=sorted(HeteroRiskGNN.POOLING_MODES))
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--weight-decay", type=float, default=1e-3)
    parser.add_argument("--no-history", action="store_true",
                        help="ignore the v5.1 pre-merge history features even if the samples have them")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    if args.graphs is not None:
        packed = load_packed_graphs(args.graphs)
        records = [{"sample_id": graph.sample_id, "repo": graph.sample_id.split("#")[0]} for graph in packed]
    else:
        records = discover_coupling_samples(args.data_dir)
    if args.split.is_file():
        split = json.loads(args.split.read_text(encoding="utf-8"))
    else:
        split = repository_split(records)
        args.split.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    where = {repo: name for name, repos in split.items() for repo in repos}
    missing = sorted({record["repo"] for record in records} - set(where))
    if missing:
        print(f"Split file does not cover repositories: {missing}")
        return 2
    graphs = {name: [] for name in ("train", "validation", "test")}
    loaded = packed if args.graphs is not None else (load_coupling_graph(record) for record in records)
    for record, graph in zip(records, loaded):
        graphs[where[record["repo"]]].append(graph)
    print(f"Loaded {len(records)} graphs in {time.perf_counter() - started:.0f}s: "
          + ", ".join(f"{name} {len(items)} ({sum(int(g.y) for g in items)} risky)" for name, items in graphs.items()))
    mean, std = fit_scaler(graphs["train"])
    for items in graphs.values():
        for graph in items:
            apply_scaler(graph, mean, std)
    every = [graph for items in graphs.values() for graph in items]
    use_history = not args.no_history and all(hasattr(graph, "hist") for graph in every)
    if not args.no_history and not use_history and any(hasattr(graph, "hist") for graph in every):
        print("Some samples have no history.json: training WITHOUT history features")
    history_mean = history_std = None
    if use_history:
        history_mean, history_std = fit_history_scaler(graphs["train"])
        for graph in every:
            apply_history_scaler(graph, history_mean, history_std)
    else:
        for graph in every:
            if hasattr(graph, "hist"):
                del graph.hist
    args.history_dim = len(HISTORY_FEATURE_NAMES) if use_history else 0
    args.history_mean, args.history_std = history_mean, history_std
    print(f"History features: {'on' if use_history else 'off'}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for seed in args.seeds:
        runs.append(train_one(seed, graphs, mean, std, args))
    summary = {"split": split, "input_features": list(INPUT_FEATURE_NAMES), "seeds": args.seeds,
               "settings": {key: getattr(args, key) for key in ("epochs", "patience", "batch_size", "hidden_channels",
                                                                "layers", "learning_rate", "pooling", "dropout",
                                                                "weight_decay", "history_dim")},
               "runs": runs}
    for metric in ("f1", "pr_auc_average_precision", "precision", "recall"):
        values = [run["test"][metric] for run in runs]
        summary[f"test_{metric}_mean"] = statistics.mean(values)
        summary[f"test_{metric}_std"] = statistics.pstdev(values)
    (args.output_dir / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key.startswith("test_")}, indent=2))
    return 0


def train_one(seed: int, graphs, mean, std, args) -> dict:
    seed_everything(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HeteroRiskGNN(graphs["train"][0].metadata(), len(INPUT_FEATURE_NAMES), args.hidden_channels,
                          layers=args.layers, pooling_mode=args.pooling, dropout=args.dropout,
                          history_dim=args.history_dim).to(device)
    positives = sum(int(graph.y) for graph in graphs["train"])
    criterion = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([(len(graphs["train"]) - positives) / max(positives, 1)], device=device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    loader = DataLoader(graphs["train"], batch_size=args.batch_size, shuffle=True)
    best_state, best_score, stale = copy.deepcopy(model.state_dict()), -1.0, 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for batch in loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch), batch.y.view(-1))
            loss.backward()
            optimizer.step()
            total += float(loss) * int(batch.num_graphs)
        labels, scores, _ = predict(model, graphs["validation"], device)
        validation_ap = binary_metrics(labels, scores)["pr_auc_average_precision"]
        print(f"seed={seed} epoch={epoch:02d} train_loss={total / len(graphs['train']):.4f} "
              f"validation_pr_auc={validation_ap:.4f}", flush=True)
        if validation_ap > best_score + 1e-4:      # keep the epoch that ranks validation PRs best
            best_state, best_score, stale = copy.deepcopy(model.state_dict()), validation_ap, 0
        else:
            stale += 1
            if stale >= args.patience:
                break
    model.load_state_dict(best_state)
    results = {"seed": seed}
    outputs = {}
    for name in ("train", "validation", "test"):
        outputs[name] = predict(model, graphs[name], device)
    threshold = best_f1_threshold(*outputs["validation"][:2])
    for name in ("train", "validation", "test"):
        results[name] = binary_metrics(outputs[name][0], outputs[name][1], threshold)
    results["threshold"] = threshold
    run_dir = args.output_dir / f"seed_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state_dict": model.state_dict(), "metadata": graphs["train"][0].metadata(),
                "feature_names": list(INPUT_FEATURE_NAMES), "feature_mean": mean, "feature_std": std,
                "hidden_channels": args.hidden_channels, "layers": args.layers, "pooling_mode": args.pooling,
                "dropout": args.dropout, "history_dim": args.history_dim, "history_feature_names": list(HISTORY_FEATURE_NAMES),
                "history_mean": args.history_mean, "history_std": args.history_std,
                "threshold": threshold, "seed": seed}, run_dir / "model.pt")
    with (run_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "label", "score"])
        for name in ("train", "validation", "test"):
            labels, scores, ids = outputs[name]
            writer.writerows([sample_id, name, label, f"{score:.6f}"] for sample_id, label, score in zip(ids, labels, scores))
    embeddings = {}
    model.eval()
    with torch.no_grad():
        for name in ("train", "validation", "test"):
            for batch in DataLoader(graphs[name], batch_size=64):
                vectors = model.encode(batch.to(device)).cpu()
                for sample_id, vector in zip(batch.sample_id, vectors):
                    embeddings[sample_id] = vector
    torch.save(embeddings, run_dir / "embeddings.pt")
    print(f"seed={seed} test={json.dumps({k: round(v, 3) for k, v in results['test'].items() if isinstance(v, float)})}")
    return results


def predict(model, graphs, device):
    model.eval()
    labels, scores, ids = [], [], []
    with torch.no_grad():
        for batch in DataLoader(graphs, batch_size=64):
            batch = batch.to(device)
            scores.extend(torch.sigmoid(model(batch)).cpu().tolist())
            labels.extend(int(value) for value in batch.y.view(-1).cpu().tolist())
            ids.extend(batch.sample_id)
    return labels, scores, ids


def best_f1_threshold(labels, scores) -> float:
    candidates = sorted(set([0.5] + list(scores)))
    return max(candidates, key=lambda t: (binary_metrics(labels, scores, t)["f1"], -abs(t - 0.5)))


if __name__ == "__main__":
    raise SystemExit(main())
