"""Write one explanation file per PR (``attribution_v5/1``) for the v5 GNN.

    python scripts/explain_coupling_v5.py --data-dir data/coupling_samples_v5 --clones data/repositories \
        --checkpoint data/gnn_v5/seed_1/model.pt --output-dir data/xai_v5 --split-name test --limit 200

For each chosen sample: re-analyse the PR's two commits (needed to know which edges the PR
added and each module's coupling before/after), load the exact 3-hop graph the model scored,
run edge Integrated Gradients, node Integrated Gradients and GNNExplainer, measure
unfaithfulness for both explainers, and write ``<owner>__<repo>__<number>.json``.
Samples are chosen with a fixed seed: half from the PRs the model calls degrading, half from
the rest (or all of them if fewer). Re-running skips files that already exist.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from src.dataset.coupling_builder import Snapshotter, analyse  # noqa: E402
from src.dataset.future_coupling import coupling_summary  # noqa: E402
from src.ml.coupling_data import (  # noqa: E402
    INPUT_FEATURE_NAMES, apply_scaler, discover_coupling_samples, load_coupling_graph,
)
from src.ml.hetero_gnn import HeteroRiskGNN  # noqa: E402
from src.xai.coupling_attribution import (  # noqa: E402
    LogitModel, build_context, edge_integrated_gradients, gnnexplainer_edges, hunk_effects,
    node_integrated_gradients, parse_hunks, ranked_edges, ranked_nodes, unfaithfulness,
)

SCHEMA = "attribution_v5/1"
SPLIT_OUT = {"train": "train", "validation": "val", "test": "test"}


def file_name(sample_id: str) -> str:
    repo, number = sample_id.split("#")
    return f"{repo.replace('/', '__')}__{int(number)}.json"


def load_model(checkpoint_path: Path) -> tuple[LogitModel, dict]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    gnn = HeteroRiskGNN(checkpoint["metadata"], len(checkpoint["feature_names"]), checkpoint["hidden_channels"],
                        layers=checkpoint["layers"], pooling_mode=checkpoint["pooling_mode"])
    gnn.load_state_dict(checkpoint["model_state_dict"])
    gnn.eval()
    for parameter in gnn.parameters():
        parameter.requires_grad_(False)
    if list(checkpoint["feature_names"]) != list(INPUT_FEATURE_NAMES):
        raise SystemExit("Checkpoint feature names do not match the current code")
    return LogitModel(gnn).eval(), checkpoint


def choose(records: list[dict], scores: dict[str, float], threshold: float, limit: int, seed: int) -> list[dict]:
    flagged = [r for r in records if scores.get(r["sample_id"], 0.0) >= threshold]
    rest = [r for r in records if scores.get(r["sample_id"], 0.0) < threshold]
    rng = random.Random(seed)
    rng.shuffle(flagged)
    rng.shuffle(rest)
    half = limit // 2
    picked = flagged[:half] + rest[:limit - min(half, len(flagged))]
    return sorted(picked[:limit], key=lambda r: r["sample_id"])


def explain_sample(record: dict, split_name: str, checkpoint_path: str, clones: str, output_dir: str,
                   settings: dict, steps: int, gnnexplainer_epochs: int) -> dict:
    started = time.perf_counter()
    target = Path(output_dir) / file_name(record["sample_id"])
    if target.is_file():
        return {"sample_id": record["sample_id"], "status": "existing"}
    model, checkpoint = load_model(Path(checkpoint_path))
    repo_dir = Path(clones) / record["repo"].replace("/", "__")
    snapshots = Snapshotter(repo_dir, Path(clones) / "_worktrees_xai" / f"{record['repo'].replace('/', '__')}_{os.getpid()}")
    before_graph, _ = analyse(snapshots.checkout(record["before_commit_sha"]), settings)
    after_graph, _ = analyse(snapshots.checkout(record["merge_commit_sha"]), settings)
    context = build_context(before_graph, after_graph)
    before_summary, after_summary = coupling_summary(before_graph), coupling_summary(after_graph)

    graph = load_coupling_graph(record)
    apply_scaler(graph, checkpoint["feature_mean"], checkpoint["feature_std"])
    edge_ig = edge_integrated_gradients(model, graph, steps=steps)
    node_ig = node_integrated_gradients(model, graph, steps=steps)
    explainer_masks = gnnexplainer_edges(model, graph, epochs=gnnexplainer_epochs) if gnnexplainer_epochs else None
    logit = edge_ig["score"]
    probability = float(torch.sigmoid(torch.tensor(logit)))
    threshold = float(checkpoint["threshold"])

    nodes = ranked_nodes(graph, node_ig["attributions"], context, limit=10_000)
    diff = (Path(record["_dir"]) / record.get("diff_path", "diff.patch")).read_text(encoding="utf-8", errors="replace")
    touched = record["touched_modules"]
    before_cyclic, after_cyclic = set(before_summary["cyclic_modules"]), set(after_summary["cyclic_modules"])
    evidence = {}
    for module in touched:
        old, new = before_summary["modules"].get(module, {}), after_summary["modules"].get(module, {})
        evidence[module] = {"ca_before": old.get("ca"), "ce_before": old.get("ce"),
                            "ca_after": new.get("ca"), "ce_after": new.get("ce"),
                            "in_import_cycle": module in after_cyclic}
    metrics = json.loads((Path(record["_dir"]) / "metrics.json").read_text(encoding="utf-8"))
    label_info = json.loads((Path(record["_dir"]) / "label.json").read_text(encoding="utf-8"))
    payload = {
        "schema": SCHEMA, "sample_id": record["sample_id"], "repo": record["repo"], "title": record.get("title", ""),
        "merged_at": record["merged_at"], "split": SPLIT_OUT[split_name],
        "label": record["label"], "label_reason": record["label_reason"],
        "risk_score": round(probability, 6), "threshold": round(threshold, 6),
        "predicted_degrading": probability >= threshold,
        # The GNN alone is explained here (no diff branch), so diff = 0 and the parts add up to
        # the GNN logit: base = score when every node looks like an average training node.
        "layer_a": {"base": round(node_ig["baseline_score"], 6),
                    "structure_gnn": round(logit - node_ig["baseline_score"], 6), "diff": 0.0},
        "logit": round(logit, 6),
        "changed_files": record["changed_python_files"], "touched_modules": touched,
        "top_edges": ranked_edges(graph, edge_ig["attributions"], context, limit=30, gnnexplainer=explainer_masks),
        "top_nodes": nodes[:20],
        "module_evidence": evidence,
        "pr_creates_cycle": bool(label_info.get("pr_creates_cycle")),
        "new_cycle_modules": sorted((after_cyclic - before_cyclic) & set(touched)),
        "structural_delta": {name: metrics["delta"][name] for name in (
            "internal_import_edge_count", "global_access_edge_count", "dependency_density",
            "max_out_degree_centrality", "mean_clustering_coefficient", "structural_entropy",
            "cyclic_component_count") if name in metrics["delta"]},
        "top_hunks": hunk_effects(parse_hunks(diff), nodes, limit=3),
        "unfaithfulness": round(unfaithfulness(model, graph, edge_ig["attributions"], top_k=30), 6),
        "explainer": "integrated_gradients_edge",
        "checks": {
            "edge_ig_completeness_gap": round(edge_ig["completeness_gap"], 6),
            "edge_ig_baseline_logit": round(edge_ig["baseline_score"], 6),
            "node_ig_completeness_gap": round(node_ig["completeness_gap"], 6),
            "gnnexplainer_unfaithfulness": (round(unfaithfulness(model, graph, explainer_masks, top_k=30), 6)
                                            if explainer_masks is not None else None),
            "random_edges_unfaithfulness": round(_random_unfaithfulness(model, graph, edge_ig["attributions"]), 6),
            "ig_steps": steps, "top_k": 30, "checkpoint_seed": checkpoint.get("seed"),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return {"sample_id": record["sample_id"], "status": "written", "seconds": round(time.perf_counter() - started, 1)}


def _random_unfaithfulness(model, graph, attributions, seed: int = 0) -> float:
    """Same measure for 30 random edges: the floor an explanation has to beat."""
    generator = torch.Generator().manual_seed(seed)
    random_scores = {edge_type: torch.rand(values.shape, generator=generator) for edge_type, values in attributions.items()}
    return unfaithfulness(model, graph, random_scores, top_k=30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/coupling_samples_v5")
    parser.add_argument("--clones", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "data/gnn_v5/seed_1/model.pt")
    parser.add_argument("--predictions", type=Path, default=None, help="predictions.csv next to the checkpoint")
    parser.add_argument("--split", type=Path, default=ROOT / "config/coupling_split_v5.json")
    parser.add_argument("--split-name", default="test", choices=["train", "validation", "test"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/xai_v5")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--only", nargs="*", help="explain exactly these sample ids")
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--gnnexplainer-epochs", type=int, default=100)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    split = json.loads(args.split.read_text(encoding="utf-8"))
    repos = set(split[args.split_name])
    records = [r for r in discover_coupling_samples(args.data_dir) if r["repo"] in repos]
    if args.only:
        wanted = set(args.only)
        records = [r for r in records if r["sample_id"] in wanted]
    else:
        predictions = args.predictions or args.checkpoint.parent / "predictions.csv"
        scores = {}
        for line in predictions.read_text(encoding="utf-8").splitlines()[1:]:
            sample_id, _, _, score = line.rsplit(",", 3)
            scores[sample_id] = float(score)
        threshold = float(torch.load(args.checkpoint, map_location="cpu", weights_only=False)["threshold"])
        records = choose(records, scores, threshold, args.limit, args.seed)
    print(f"Explaining {len(records)} samples from the {args.split_name} split", flush=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(r, args.split_name, str(args.checkpoint), str(args.clones), str(args.output_dir), settings, args.steps,
             args.gnnexplainer_epochs) for r in records]
    log = (args.output_dir / "explain_log.jsonl").open("a", encoding="utf-8")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(explain_sample, *job) for job in jobs]
        for index, future in enumerate(futures, 1):
            try:
                result = future.result()
            except Exception as exc:  # one broken sample must not stop the rest
                result = {"sample_id": jobs[index - 1][0]["sample_id"], "status": "failed",
                          "reason": f"{type(exc).__name__}: {exc}"[:300]}
            log.write(json.dumps(result) + "\n")
            log.flush()
            if index % 10 == 0 or result["status"] == "failed":
                print(f"{index}/{len(jobs)} {result}", flush=True)
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
