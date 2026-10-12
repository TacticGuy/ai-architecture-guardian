"""Build the chatbot's knowledge base from the real project outputs.

    python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v3.json

Reads (all found from the manifest's version):
  artifacts/gnn_embeddings_<v>.json     which PRs exist, their labels and splits
  data/fusion/<v>/metrics.json          model results (from train_fusion.py)
  data/fusion/<v>/predictions.csv       every PR's risk score
  data/xai/<v>/*.json                   explanations (from explain_prs.py), optional
  data/future_pr_samples_<v>/           PR metadata: label evidence, changed files
  artifacts/gnn_metrics_<v>.json        split cutoffs, optional
  docs/knowledge/*.md                   hand-written method notes (one card per "## " section)
Writes data/kb/<v>/cards.jsonl and kb.json. Re-run it whenever any of those change.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fusion.data import manifest_version  # noqa: E402
from src.rag.knowledge import KnowledgeError, build_cards, load_inputs, save_cards  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the chatbot knowledge base (cards) from project outputs.")
    parser.add_argument("--manifest", type=Path, required=True, help="e.g. artifacts/gnn_embeddings_v3.json")
    parser.add_argument("--fusion-dir", type=Path, help="Default: data/fusion/<version>")
    parser.add_argument("--xai-dir", type=Path, help="Default: data/xai/<version>")
    parser.add_argument("--samples-dir", type=Path, help="Default: data/future_pr_samples_<version>")
    parser.add_argument("--gnn-metrics", type=Path, help="Default: gnn_metrics_<version>.json next to the manifest")
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs/knowledge")
    parser.add_argument("--output-dir", type=Path, help="Default: data/kb/<version>")
    args = parser.parse_args(argv)

    version = manifest_version(args.manifest)
    if version is None and not (args.fusion_dir and args.output_dir):
        parser.error("cannot tell the data version from the manifest name; pass --fusion-dir and --output-dir")
    fusion_dir = args.fusion_dir or ROOT / "data/fusion" / str(version)
    xai_dir = args.xai_dir or ROOT / "data/xai" / str(version)
    samples_dir = args.samples_dir or ROOT / "data" / f"future_pr_samples_{version}"
    gnn_metrics = args.gnn_metrics or args.manifest.parent / f"gnn_metrics_{version}.json"
    output_dir = args.output_dir or ROOT / "data/kb" / str(version)
    for name, path, hint in (("manifest", args.manifest, ""),
                             ("fusion metrics", fusion_dir / "metrics.json", " Run scripts/train_fusion.py first."),
                             ("fusion predictions", fusion_dir / "predictions.csv", " Run scripts/train_fusion.py first.")):
        if not path.is_file():
            print(f"Missing {name}: {path}.{hint}")
            return 2
    for name, path in (("XAI explanations", xai_dir), ("PR samples", samples_dir), ("knowledge notes", args.docs_dir)):
        if not path.is_dir():
            print(f"Note: no {name} at {path}; those cards will be missing.")

    try:
        inputs = load_inputs(manifest_path=args.manifest, fusion_dir=fusion_dir, xai_dir=xai_dir,
                             samples_dir=samples_dir, gnn_metrics_path=gnn_metrics)
        cards = build_cards(inputs, args.docs_dir)
    except KnowledgeError as exc:
        print(f"Inputs do not agree: {exc}")
        return 2

    sources = {"manifest": _describe(args.manifest), "metrics": _describe(fusion_dir / "metrics.json"),
               "predictions": _describe(fusion_dir / "predictions.csv"),
               "explained_prs": sorted(inputs["explanations"]), "metadata_prs": len(inputs["metadata"]),
               "docs": sorted(path.name for path in args.docs_dir.glob("*.md")) if args.docs_dir.is_dir() else []}
    save_cards(output_dir, cards, sources)
    kinds = {}
    for card in cards:
        kinds[card.kind] = kinds.get(card.kind, 0) + 1
    explained = sum(1 for card in cards if card.kind == "pr" and card.meta.get("explained"))
    print(f"Built {len(cards)} cards: " + ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items())))
    print(f"PR cards with explanations: {explained} of {kinds.get('pr', 0)}"
          + ("" if explained == kinds.get("pr", 0) else
             " (run explain_prs.py --split all to explain the rest)"))
    print(f"Saved: {output_dir / 'cards.jsonl'}")
    return 0


def _describe(path: Path) -> dict[str, str]:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    raise SystemExit(main())
