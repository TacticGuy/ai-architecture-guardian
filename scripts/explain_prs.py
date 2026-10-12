"""Explain the fusion risk score of PRs (XAI layers A and B).

    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json            # test PRs
    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json --split all
    python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_v3.json --sample-id pallets/flask#5331

Needs the outputs of build_diff_embeddings.py and train_fusion.py for the same manifest, and
loads the same CodeReviewer model (already downloaded on the machine that built the vectors).

Writes data/xai/<version>/:
  <repo>__<name>__<number>.json   per PR: score, structure-vs-diff split, hunks ranked by effect
  summary.csv                     one line per PR

Safety checks (the run stops instead of explaining the wrong thing):
  * the fusion model must have been trained on exactly these input files (sha256 match);
  * the encoder settings must equal the ones stored with the CodeReviewer vectors;
  * re-encoding each full diff must reproduce its saved vector.
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
from src.semantic.diff_encoder import DiffEncoder, EncoderSettings  # noqa: E402
from src.utils.config import load_settings  # noqa: E402
from src.xai.explain import ExplanationError, explain_pr  # noqa: E402

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
    parser.add_argument("--batch-size", type=int, default=EncoderSettings.batch_size)
    parser.add_argument("--device", default="cpu", help="cpu (default), cuda, or auto")
    args = parser.parse_args(argv)
    if args.max_hunks < 1:
        parser.error("--max-hunks must be >= 1")

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
    for name, path, hint in (("manifest", args.manifest, ""), ("GNN embeddings", gnn_path, ""),
                             ("CodeReviewer embeddings", diff_path, " Run scripts/build_diff_embeddings.py first."),
                             ("fusion model", fusion_path, " Run scripts/train_fusion.py first.")):
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
    diff_paths = _diff_paths(samples_dir)
    missing = [sample_id for sample_id in selected if sample_id not in diff_paths]
    if missing:
        print(f"No diff.patch under {samples_dir} for: {', '.join(missing)}")
        return 2

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
        print(f"[{number}/{len(selected)}] {sample_id} risk={result['probability']:.3f} "
              f"structure={parts['structure_gnn']:+.2f} diff={parts['diff_codereviewer']:+.2f} "
              f"top hunk {where} ({time.perf_counter() - started:.0f}s)")

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


def _diff_paths(samples_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for metadata_path in sorted(samples_dir.glob("*/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        diff_path = metadata_path.parent / metadata.get("diff_path", "diff.patch")
        if isinstance(metadata.get("sample_id"), str) and diff_path.is_file():
            paths[metadata["sample_id"]] = diff_path
    return paths


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
            "hunks_explained": report["hunk_counts"]["explained"]}


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
