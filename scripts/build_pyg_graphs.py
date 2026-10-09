"""Convert analysed repositories into PyTorch Geometric HeteroData files (point 5)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.repository.clone import repository_id
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build PyG HeteroData graphs from point 2-4 analysis output (point 5).")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--repo", help="One configured, already-analysed repository, e.g. psf/requests")
    selection.add_argument("--all", action="store_true", help="All enabled, already-analysed repositories")
    selection.add_argument("--analysis-dir", type=Path, help="One explicit analysis folder (with dependency_graph.json)")
    parser.add_argument("--output-dir", type=Path, help="Where graph folders are written (default: pyg_output_directory)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logger = configure_logging(ROOT / "logs/pipeline.log", args.verbose)
    settings = load_settings(ROOT / "config/settings.json")

    try:
        from src.ml.hetero_data import build_hetero_data, load_hetero_data, save_hetero_data
    except ImportError as exc:
        print(f"PyTorch / PyTorch Geometric is not installed ({exc}). Run: pip install -r requirements.txt")
        return 1

    output_root = args.output_dir or ROOT / settings["pyg_output_directory"]
    targets: list[tuple[str, Path]] = []
    if args.analysis_dir:
        targets.append((args.analysis_dir.resolve().name, args.analysis_dir.resolve()))
    else:
        repositories = enabled_repositories(load_repositories(ROOT / "config/repositories.json"))
        if args.repo:
            repositories = [repo for repo in repositories if repository_id(repo).lower() == args.repo.lower()]
            if not repositories:
                parser.error(f"{args.repo!r} is not an enabled configured repository")
        analysis_root = ROOT / settings["analysis_output_directory"]
        targets = [(repository_id(repo).replace("/", "__"), analysis_root / repository_id(repo).replace("/", "__"))
                   for repo in repositories]

    failures: list[str] = []
    for name, analysis_dir in targets:
        graph_file, features_file = analysis_dir / "dependency_graph.json", analysis_dir / "node_features.json"
        if not graph_file.is_file() or not features_file.is_file():
            failures.append(f"{name}: no analysis found in {analysis_dir}; run analyse_repositories.py first")
            continue
        try:
            graph = json.loads(graph_file.read_text(encoding="utf-8"))
            features = json.loads(features_file.read_text(encoding="utf-8"))
            data = build_hetero_data(graph, features)
            destination = output_root / name / "graph.pt"
            save_hetero_data(data, destination)
            load_hetero_data(destination)  # prove the saved file loads before reporting success
        except (OSError, ValueError) as exc:
            failures.append(f"{name}: {exc}")
            logger.exception("PyG conversion failed for %s", name)
            continue
        nodes = {node_type: data[node_type].num_nodes for node_type in data.node_types}
        used = {edge_type: data[edge_type].num_edges for edge_type in data.edge_types if data[edge_type].num_edges}
        print(f"Built {name}: {sum(nodes.values())} nodes, {sum(used.values())} edges, "
              f"{len(used)}/{len(data.edge_types)} edge types used -> {destination}")
        print("  nodes: " + ", ".join(f"{node_type}={count}" for node_type, count in nodes.items()))
        logger.info("Wrote PyG graph for %s to %s", name, destination)

    if failures:
        print("Failures:\n" + "\n".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
