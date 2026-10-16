"""Explain the fusion risk score of PRs (XAI layers A and B).

    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json            # test PRs
    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json --split all
    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json --sample-id pallets/flask#5331

Needs the outputs of build_diff_embeddings.py and train_fusion.py for the same manifest, and
loads the same CodeReviewer model (already downloaded on the machine that built the vectors).

Writes data/xai/<version>/:
  <repo>__<name>__<number>.json   per PR: score, structure-vs-diff split (A), hunks ranked by
                                  effect (B), code files ranked by effect on the structure part (C)
  summary.csv                     one line per PR

Layer C uses the GNN checkpoint named in the manifest (artifacts/gnn_future_risk_<version>.pt)
and each PR's before/graph.pt. Skip it with --no-graph.

Safety checks (the run stops instead of explaining the wrong thing):
  * the fusion model must have been trained on exactly these input files (sha256 match);
  * the encoder settings must equal the ones stored with the CodeReviewer vectors;
  * re-encoding each full diff must reproduce its saved vector;
  * the GNN checkpoint must reproduce each PR's saved GNN vector from its graph.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from src.fusion.data import AlignmentError, load_aligned, manifest_version  # noqa: E402
from src.fusion.model import FusionModel  # noqa: E402
from src.ml.gnn_inference import load_gnn_checkpoint, load_gnn_model, prepare_graph  # noqa: E402
from src.semantic.diff_encoder import DiffEncoder, EncoderSettings  # noqa: E402
from src.utils.config import load_settings  # noqa: E402
from src.xai.explain import ExplanationError, explain_pr  # noqa: E402
from src.xai.graph import explain_graph  # noqa: E402

SCHEMA_VERSION = 1
EncoderFactory = Callable[[str, EncoderSettings, str], DiffEncoder]


def main(argv: list[str] | None = None, encoder_factory: EncoderFactory | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain fusion risk scores (structure vs diff, top hunks).")
    parser.add_argument("--manifest", type=Path, required=True, help="e.g. artifacts/gnn_embeddings_v3.json")
    parser.add_argument("--split", choices=("train", "validation", "test", "all"), default="test",
                        help="Which PRs to explain (default: test)")
    parser.add_argument("--sample-id", action="append", default=[], help="Explain only these PRs")
    parser.add_argument("--max-hunks", type=int, default=20, help="Largest hunks tested per PR (default 20)")
    parser.add_argument("--gnn", type=Path, help="Default: the file named in the manifest")
    parser.add_argument("--diff", type=Path, help="Default: data/embeddings/<model>__<manifest name>/embeddings.pt")
    parser.add_argument("--diff-model", default="microsoft/codereviewer")
    parser.add_argument("--fusion-model", type=Path, help="Default: data/fusion/<version>/fusion_model.pt")
    parser.add_argument("--samples-dir", type=Path, help="Default: data/future_pr_samples_<version>")
    parser.add_argument("--output-dir", type=Path, help="Default: data/xai/<version>")
    parser.add_argument("--gnn-checkpoint", type=Path,
                        help="Default: the checkpoint named in the manifest, next to it (layer C)")
    parser.add_argument("--no-graph", action="store_true", help="Skip layer C (which code files matter)")
    parser.add_argument("--graph-steps", type=int, default=64, help="Integrated Gradients steps (layer C)")
    parser.add_argument("--top-files", type=int, default=10, help="Files listed per PR (layer C)")
    parser.add_argument("--batch-size", type=int, default=EncoderSettings.batch_size)
    parser.add_argument("--device", default="cpu", help="cpu (default), cuda, or auto")
    args = parser.parse_args(argv)
    if args.max_hunks < 1 or args.graph_steps < 1 or args.top_files < 1:
        parser.error("--max-hunks, --graph-steps and --top-files must be >= 1")

    version = manifest_version(args.manifest)
    if version is None and not (args.samples_dir and args.fusion_model and args.output_dir):
        parser.error("cannot tell the data version from the manifest name; pass --samples-dir, "
                     "--fusion-model and --output-dir")
    gnn_path = args.gnn or _default_gnn_path(args.manifest)
    diff_path = args.diff or (ROOT / "data/embeddings"
                              / f"{args.diff_model.replace('/', '__')}__{args.manifest.stem}" / "embeddings.pt")
    fusion_path = args.fusion_model or ROOT / "data/fusion" / str(version) / "fusion_model.pt"
    samples_dir = args.samples_dir or ROOT / "data" / f"future_pr_samples_{version}"
    output_dir = args.output_dir or ROOT / "data/xai" / str(version)
    checkpoint_path = None if args.no_graph else (args.gnn_checkpoint or _default_checkpoint_path(args.manifest))
    for name, path, hint in (("manifest", args.manifest, ""), ("GNN embeddings", gnn_path, ""),
                             ("CodeReviewer embeddings", diff_path, " Run scripts/build_diff_embeddings.py first."),
                             ("fusion model", fusion_path, " Run scripts/train_fusion.py first."),
                             *((("GNN checkpoint", checkpoint_path,
                                 " Copy the teammate's checkpoint there, or skip layer C with --no-graph."),)
                               if checkpoint_path else ())):
        if not path.is_file():
            print(f"Missing {name}: {path}.{hint}")
            return 2

    try:
        data = load_aligned(args.manifest, gnn_path, diff_path)
    except AlignmentError as exc:
        print(f"Inputs do not line up: {exc}")
        return 2
    saved = torch.load(fusion_path, weights_only=True)
    stale = [key for key in ("manifest", "gnn_embeddings", "diff_embeddings")
             if saved.get("sources", {}).get(key, {}).get("sha256") != data.sources[key]["sha256"]]
    if stale:
        print(f"The fusion model was trained on different {', '.join(stale)}. Re-run scripts/train_fusion.py.")
        return 2
    model = FusionModel.from_state(saved["models"][saved["main"]])
    threshold = model.threshold

    selected = _select(data, args.split, args.sample_id)
    if isinstance(selected, str):
        print(selected)
        return 2
    diff_paths, graph_paths = _sample_paths(samples_dir)
    missing = [sample_id for sample_id in selected if sample_id not in diff_paths]
    if missing:
        print(f"No diff.patch under {samples_dir} for: {', '.join(missing)}")
        return 2
    if checkpoint_path:
        missing = [sample_id for sample_id in selected if sample_id not in graph_paths]
        if missing:
            print(f"No before/graph.pt under {samples_dir} for: {', '.join(missing)} (or use --no-graph)")
            return 2
        checkpoint = load_gnn_checkpoint(checkpoint_path)
        gnn = load_gnn_model(checkpoint, "cpu")
        print(f"Layer C: GNN checkpoint {checkpoint_path.name}")

    store = torch.load(diff_path, weights_only=True)
    stored_settings = store["encoder"]
    settings = EncoderSettings(max_tokens=stored_settings["max_tokens"], stride=stored_settings["stride"],
                               max_chunks=stored_settings["max_chunks"], batch_size=args.batch_size,
                               graph_files_only=stored_settings["graph_files_only"])
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    print(f"Loading {stored_settings['model_name']} on {device}...")
    encoder = (encoder_factory or _pretrained)(stored_settings["model_name"], settings, device)
    if encoder.describe() != stored_settings:
        print(f"Encoder settings differ from the ones used for the vectors:\n  stored : {stored_settings}\n"
              f"  current: {encoder.describe()}")
        return 2
    analysis_settings = load_settings(ROOT / "config/settings.json")["static_analysis"]

    output_dir.mkdir(parents=True, exist_ok=True)
    row_of = {sample_id: row for row, sample_id in enumerate(data.sample_ids)}
    summary: list[dict[str, Any]] = []
    failures: list[str] = []
    print(f"Explaining {len(selected)} PR(s), up to {args.max_hunks} hunks each | threshold {threshold:.3f}")
    for number, sample_id in enumerate(selected, 1):
        row, started = row_of[sample_id], time.perf_counter()
        try:
            result = explain_pr(model=model, encoder=encoder, analysis_settings=analysis_settings,
                                diff_text=diff_paths[sample_id].read_text(encoding="utf-8", errors="replace"),
                                gnn=data.gnn[row], stored_diff=data.diff[row], max_hunks=args.max_hunks)
            if checkpoint_path:
                result["graph"] = explain_graph(
                    gnn=gnn, graph=prepare_graph(graph_paths[sample_id], checkpoint), fusion=model,
                    diff=data.diff[row], stored_gnn=data.gnn[row], feature_names=list(checkpoint["feature_names"]),
                    steps=args.graph_steps, top_files=args.top_files)
        except (ExplanationError, ValueError, OSError) as exc:
            failures.append(f"{sample_id}: {exc}")
            print(f"[{number}/{len(selected)}] FAILED {sample_id}: {exc}")
            if isinstance(exc, ExplanationError):
                break                                   # same cause for every PR; stop early
            continue
        report = {"schema_version": SCHEMA_VERSION, "sample_id": sample_id, "split": data.splits[row],
                  "label": int(data.labels[row]), "threshold": threshold,
                  "predicted_risky": result["probability"] >= threshold, **result,
                  "note": "Shows what the model relies on, not proof of what causes risk."}
        _write_json(output_dir / f"{_file_name(sample_id)}.json", report)
        summary.append(_summary_row(report))
        top = result["hunks"][0] if result["hunks"] else None
        where = f"{top['file']}:{top['new_lines'][0]}-{top['new_lines'][1]} ({top['effect_on_risk']:+.3f})" if top else "-"
        parts = result["contributions"]
        graph = result.get("graph")
        top_file = (f" | top file {graph['files'][0]['file']} ({graph['files'][0]['attribution']:+.2f})"
                    if graph and graph["files"] else "")
        print(f"[{number}/{len(selected)}] {sample_id} risk={result['probability']:.3f} "
              f"structure={parts['structure_gnn']:+.2f} diff={parts['diff_codereviewer']:+.2f} "
              f"top hunk {where}{top_file} ({time.perf_counter() - started:.0f}s)")

    if summary:
        _write_summary(output_dir / "summary.csv", summary)
        print(f"Saved {len(summary)} explanation(s) in {output_dir}")
    if failures:
        print("Failures:\n" + "\n".join(failures))
        return 1
    return 0


def _select(data, split: str, wanted: list[str]) -> list[str] | str:
    if wanted:
        unknown = [sample_id for sample_id in wanted if sample_id not in data.sample_ids]
        return f"Not in the manifest: {', '.join(unknown)}" if unknown else list(dict.fromkeys(wanted))
    return [sample_id for sample_id, value in zip(data.sample_ids, data.splits) if split in ("all", value)]


def _sample_paths(samples_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    diffs: dict[str, Path] = {}
    graphs: dict[str, Path] = {}
    for metadata_path in sorted(samples_dir.glob("*/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sample_id = metadata.get("sample_id")
        if not isinstance(sample_id, str):
            continue
        diff_path = metadata_path.parent / metadata.get("diff_path", "diff.patch")
        if diff_path.is_file():
            diffs[sample_id] = diff_path
        graph = metadata.get("before_graph_path")
        if isinstance(graph, str) and (metadata_path.parent / graph).is_file():
            graphs[sample_id] = metadata_path.parent / graph
    return diffs, graphs


def _default_checkpoint_path(manifest_path: Path) -> Path:
    try:
        named = json.loads(manifest_path.read_text(encoding="utf-8")).get("checkpoint_name")
    except (OSError, json.JSONDecodeError):
        named = None
    if not isinstance(named, str) or not named:
        version = manifest_version(manifest_path)
        named = f"gnn_future_risk_{version}.pt"
    return manifest_path.parent / named


def _default_gnn_path(manifest_path: Path) -> Path:
    try:
        named = json.loads(manifest_path.read_text(encoding="utf-8")).get("embedding_file")
    except (OSError, json.JSONDecodeError):
        named = None
    return manifest_path.parent / named if isinstance(named, str) and named else manifest_path.with_suffix(".pt")


def _file_name(sample_id: str) -> str:
    return sample_id.replace("/", "__").replace("#", "__")


def _summary_row(report: dict[str, Any]) -> dict[str, Any]:
    parts, top = report["contributions"], (report["hunks"][0] if report["hunks"] else {})
    return {"sample_id": report["sample_id"], "split": report["split"], "label": report["label"],
            "probability": f"{report['probability']:.6f}", "predicted_risky": int(report["predicted_risky"]),
            "structure_gnn": f"{parts['structure_gnn']:.4f}", "diff_codereviewer": f"{parts['diff_codereviewer']:.4f}",
            "base_logit": f"{parts['base_logit']:.4f}", "top_hunk_file": top.get("file", ""),
            "top_hunk_lines": "-".join(str(value) for value in top.get("new_lines", [])),
            "top_hunk_effect": f"{top['effect_on_risk']:.6f}" if top else "",
            "hunks_explained": report["hunk_counts"]["explained"],
            **_graph_summary(report.get("graph"))}


def _graph_summary(graph: dict[str, Any] | None) -> dict[str, str]:
    if not graph:
        return {"gnn_probability": "", "top_file": "", "top_file_effect": "", "top_file_touched": "",
                "touched_files_total": "", "untouched_files_total": ""}
    top = graph["files"][0] if graph["files"] else {}
    return {"gnn_probability": f"{graph['gnn_probability']:.6f}", "top_file": top.get("file", ""),
            "top_file_effect": f"{top['attribution']:.4f}" if top else "",
            "top_file_touched": int(top.get("touched", False)) if top else "",
            "touched_files_total": f"{graph['touched_files_total']:.4f}",
            "untouched_files_total": f"{graph['untouched_files_total']:.4f}"}


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _pretrained(model_name: str, settings: EncoderSettings, device: str) -> DiffEncoder:
    return DiffEncoder.from_pretrained(model_name, settings, device)


if __name__ == "__main__":
    raise SystemExit(main())
