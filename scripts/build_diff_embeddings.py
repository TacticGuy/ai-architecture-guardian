"""Build one diff embedding per PR sample (points 9-11), keyed by sample_id.

Two ways to choose samples:
  * manifest mode (use this for fusion):  --manifest artifacts/gnn_embeddings_v3.json
      Encodes EXACTLY the sample_ids in the GNN manifest, copies their authoritative
      label and train/validation/test split, never uses the full-diff fallback, and
      verifies the result (same ID set, unique IDs, labels, split counts) before finishing.
      Samples in the folder but not in the manifest (e.g. purged ones) are ignored.
  * folder mode: every */*/metadata.json under --samples-dir.

Output (default ``data/embeddings/<model>[__<manifest name>]/``):
  embeddings.pt  dict: sample_ids, embeddings [N, dim], labels, splits, model settings, ...
  index.csv      sample_id,row,label,split,... one line per embedding

Join with other outputs ONLY by ``sample_id`` (never by row order). Re-running only
encodes samples that are new, or whose diff.patch changed since they were encoded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from src.semantic.diff_encoder import DEFAULT_MODEL, DiffEncoder, EncoderSettings  # noqa: E402
from src.utils.config import load_settings  # noqa: E402

SCHEMA_VERSION = 2
EncoderFactory = Callable[[str, EncoderSettings, str], DiffEncoder]


class ManifestError(ValueError):
    """The manifest and the sample folder disagree; nothing should be produced."""


def main(argv: list[str] | None = None, encoder_factory: EncoderFactory | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed PR diff.patch files with a pretrained code model.")
    parser.add_argument("--manifest", type=Path,
                        help="GNN embedding manifest (e.g. artifacts/gnn_embeddings_v3.json): encode exactly its samples")
    parser.add_argument("--samples-dir", type=Path,
                        help="Default: data/future_pr_samples_<version> with --manifest (version from the manifest "
                             "name, e.g. gnn_embeddings_v4.json -> v4), else data/future_pr_samples")
    parser.add_argument("--output-dir", type=Path, help="Default: data/embeddings/<model>[__<manifest name>]")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Hugging Face model (default {DEFAULT_MODEL})")
    parser.add_argument("--limit", type=int, help="Encode at most this many new/changed samples (trial runs)")
    parser.add_argument("--sample-id", action="append", default=[], help="Only these sample_ids (folder mode)")
    parser.add_argument("--max-chunks", type=int, default=EncoderSettings.max_chunks)
    parser.add_argument("--batch-size", type=int, default=EncoderSettings.batch_size)
    parser.add_argument("--keep-test-files", action="store_true",
                        help="Encode the whole diff instead of only files the graph analyses")
    parser.add_argument("--device", default="cpu", help="cpu (default), cuda, or auto")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.manifest and args.sample_id:
        parser.error("--sample-id cannot be combined with --manifest (the manifest decides the samples)")
    if args.manifest and not args.samples_dir and manifest_version(args.manifest) is None:
        parser.error(f"cannot tell the data version from '{args.manifest.name}' (expected a name ending in _v<number>, "
                     "e.g. gnn_embeddings_v4.json). Pass --samples-dir.")

    settings = EncoderSettings(max_chunks=args.max_chunks, batch_size=args.batch_size,
                               graph_files_only=not args.keep_test_files)
    analysis_settings = load_settings(ROOT / "config/settings.json")["static_analysis"]
    samples_dir = args.samples_dir or default_samples_dir(args.manifest, ROOT)
    model_slug = args.model.replace("/", "__").replace("\\", "__")
    if args.output_dir:
        output_dir = args.output_dir
    elif args.manifest:
        output_dir = ROOT / "data/embeddings" / f"{model_slug}__{args.manifest.stem}"
    else:
        output_dir = ROOT / "data/embeddings" / model_slug
    store_path, index_path = output_dir / "embeddings.pt", output_dir / "index.csv"

    print(f"Samples folder: {samples_dir}")
    try:
        samples = discover_samples(samples_dir)
        if not samples:
            print(f"No samples with metadata.json + diff.patch found under {samples_dir}")
            return 2
        manifest = None
        if args.manifest:
            manifest = load_manifest(args.manifest)
            samples, ignored = select_manifest_samples(samples, manifest)
            print(f"Manifest: {args.manifest.name} | {len(samples)} samples | splits "
                  f"{dict(Counter(row['split'] for row in manifest['rows']))} | ignored in folder (not in manifest): "
                  f"{len(ignored)}{' -> ' + ', '.join(ignored) if ignored else ''}")
        elif args.sample_id:
            samples = select_ids(samples, args.sample_id)
    except (ManifestError, ValueError) as exc:
        print(f"Dataset problem: {exc}")
        return 2

    store = load_store(store_path)
    if store and manifest and (store.get("manifest") or {}).get("sha256") != manifest["identity"]["sha256"]:
        print(f"{store_path} was built for a different manifest. Use --output-dir or delete that folder.")
        return 2
    rows = {sample_id: row for row, sample_id in enumerate(store["sample_ids"])} if store else {}
    pending = [sample for sample in samples
               if sample["sample_id"] not in rows or store["diff_sha256"][rows[sample["sample_id"]]] != sample["diff_sha256"]]
    todo = pending[: args.limit] if args.limit is not None else pending
    print(f"Samples: {len(samples)} | up to date: {len(samples) - len(pending)} | "
          f"new or changed: {len(pending)} | encoding now: {len(todo)}")

    failures: list[str] = []
    if todo:
        device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
        print(f"Loading {args.model} on {device} (first run downloads the model)...")
        encoder = (encoder_factory or _pretrained)(args.model, settings, device)
        described = encoder.describe()
        if store and store["encoder"] != described:
            print("These embeddings were made with different settings:\n"
                  f"  stored : {store['encoder']}\n  current: {described}\n"
                  "Mixing them would make rows incomparable. Use --output-dir for a separate run, "
                  "or delete the old output folder to rebuild everything.")
            return 2
        store = store or new_store(described, manifest)
        print(f"Model: {described['model_name']} | dim: {described['dim']} | line format: {described['line_format']}")

        for number, sample in enumerate(todo, 1):
            try:
                diff_text = sample["diff_path"].read_text(encoding="utf-8", errors="replace")
                encoded = encoder.encode_diff(diff_text, analysis_settings, allow_fallback=manifest is None)
            except (OSError, ValueError, RuntimeError) as exc:
                failures.append(f"{sample['sample_id']}: {exc}")
                print(f"[{number}/{len(todo)}] FAILED {sample['sample_id']}: {exc}")
                continue
            upsert(store, sample, encoded)
            note = " (truncated)" if encoded.truncated else ""
            note += " (test-only diff: full diff used)" if encoded.fallback_full_diff else ""
            print(f"[{number}/{len(todo)}] {sample['sample_id']} label={sample['label']}"
                  f"{' split=' + sample['split'] if sample.get('split') else ''} "
                  f"tokens={encoded.num_tokens} chunks={encoded.num_chunks}{note}")
            if number % 10 == 0:
                save_store(store_path, store)  # progress survives an interruption
        if manifest:
            reorder(store, [row["sample_id"] for row in manifest["rows"]])
        save_store(store_path, store)
    elif not store:
        print("Nothing to encode and no existing embeddings.")
        return 2
    else:
        print("Nothing to do: every embedding is up to date.")

    write_index(index_path, store)
    print(f"Encoded now: {len(todo) - len(failures)} | failed: {len(failures)} | total stored: "
          f"{len(store['sample_ids'])} | dim: {store['dim']}")
    print(f"Embeddings: {store_path}\nIndex:      {index_path}")
    if failures:
        print("Failures:\n" + "\n".join(failures))
        return 1
    if manifest:
        if args.limit is not None and len(store["sample_ids"]) < len(manifest["rows"]):
            print(f"Trial run (--limit): {len(store['sample_ids'])}/{len(manifest['rows'])} done, "
                  "full manifest check skipped. Re-run without --limit to finish.")
            return 0
        try:
            verify_against_manifest(store, manifest)
        except ManifestError as exc:
            print(f"MANIFEST CHECK FAILED: {exc}")
            return 1
        counts = Counter(store["splits"])
        print(f"Manifest check passed: {len(store['sample_ids'])} unique sample_ids = manifest set, labels match, "
              f"splits train/validation/test = {counts['train']}/{counts['validation']}/{counts['test']}, "
              f"shape {list(store['embeddings'].shape)}")
    return 0


# --- samples and manifest --------------------------------------------------------------------

def manifest_version(manifest_path: Path) -> str | None:
    """'gnn_embeddings_v4.json' -> 'v4'; None when the name carries no version."""
    match = re.search(r"_(v\d+)$", manifest_path.stem)
    return match.group(1) if match else None


def default_samples_dir(manifest_path: Path | None, root: Path) -> Path:
    """Where the diffs live by default: the folder of the same data version as the manifest."""
    if manifest_path is None:
        return root / "data/future_pr_samples"
    version = manifest_version(manifest_path)
    if version is None:
        raise ValueError(f"no version in manifest name {manifest_path.name}")
    return root / "data" / f"future_pr_samples_{version}"


def discover_samples(samples_dir: Path) -> list[dict[str, Any]]:
    """Read every ``*/*/metadata.json`` that has a diff and a 0/1 label, sorted by sample_id."""
    samples: dict[str, dict[str, Any]] = {}
    for metadata_path in sorted(samples_dir.glob("*/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sample_id, label = metadata.get("sample_id"), metadata.get("label")
        diff_path = metadata_path.parent / metadata.get("diff_path", "diff.patch")
        if not isinstance(sample_id, str) or label not in (0, 1) or not diff_path.is_file():
            continue
        if sample_id in samples:
            raise ValueError(f"sample_id {sample_id} appears twice ({samples[sample_id]['diff_path'].parent} "
                             f"and {metadata_path.parent})")
        samples[sample_id] = {"sample_id": sample_id, "label": int(label), "diff_path": diff_path,
                              "diff_sha256": hashlib.sha256(diff_path.read_bytes()).hexdigest()}
    return [samples[key] for key in sorted(samples)]


def select_ids(samples: list[dict[str, Any]], wanted_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(wanted_ids)
    unknown = sorted(wanted - {sample["sample_id"] for sample in samples})
    if unknown:
        raise ValueError(f"Unknown sample_id(s): {', '.join(unknown)}")
    return [sample for sample in samples if sample["sample_id"] in wanted]


def load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ManifestError(f"{path} has no 'rows'")
    ids = [row.get("sample_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise ManifestError(f"{path} lists a sample_id more than once")
    for row in rows:
        if row.get("label") not in (0, 1) or row.get("split") not in ("train", "validation", "test"):
            raise ManifestError(f"{path}: bad label/split for {row.get('sample_id')}")
    if isinstance(manifest.get("count"), int) and manifest["count"] != len(rows):
        raise ManifestError(f"{path} says count={manifest['count']} but has {len(rows)} rows")
    manifest["identity"] = {"name": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "count": len(rows)}
    return manifest


def select_manifest_samples(samples: list[dict[str, Any]], manifest: dict[str, Any]
                            ) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep exactly the manifest's samples, with the manifest's label and split.

    A sample whose metadata label disagrees with the manifest is an error, not silently fixed.
    """
    by_id = {sample["sample_id"]: sample for sample in samples}
    missing = [row["sample_id"] for row in manifest["rows"] if row["sample_id"] not in by_id]
    if missing:
        raise ManifestError(f"{len(missing)} manifest sample(s) have no diff in the folder: {', '.join(missing)}")
    selected = []
    for row in manifest["rows"]:
        sample = dict(by_id[row["sample_id"]])
        if sample["label"] != row["label"]:
            raise ManifestError(f"{row['sample_id']}: metadata label {sample['label']} != manifest label {row['label']}")
        sample["split"] = row["split"]
        selected.append(sample)
    wanted = {row["sample_id"] for row in manifest["rows"]}
    ignored = sorted((sid for sid in by_id if sid not in wanted), key=_pr_order)
    return selected, ignored


def verify_against_manifest(store: dict[str, Any], manifest: dict[str, Any]) -> None:
    ids = store["sample_ids"]
    rows = manifest["rows"]
    if len(ids) != len(set(ids)):
        raise ManifestError("duplicate sample_ids in the output")
    if set(ids) != {row["sample_id"] for row in rows}:
        raise ManifestError(f"sample_id set differs from the manifest "
                            f"(missing {sorted({row['sample_id'] for row in rows} - set(ids))}, "
                            f"extra {sorted(set(ids) - {row['sample_id'] for row in rows})})")
    expected = {row["sample_id"]: row for row in rows}
    for position, sample_id in enumerate(ids):
        if int(store["labels"][position]) != expected[sample_id]["label"]:
            raise ManifestError(f"label mismatch for {sample_id}")
        if store["splits"][position] != expected[sample_id]["split"]:
            raise ManifestError(f"split mismatch for {sample_id}")
    if Counter(store["splits"]) != Counter(row["split"] for row in rows):
        raise ManifestError(f"split counts {dict(Counter(store['splits']))} differ from the manifest")
    if tuple(store["embeddings"].shape) != (len(rows), store["dim"]):
        raise ManifestError(f"embedding shape {tuple(store['embeddings'].shape)} != {(len(rows), store['dim'])}")
    if not bool(torch.isfinite(store["embeddings"]).all()):
        raise ManifestError("embeddings contain NaN or infinity")


def _pr_order(sample_id: str) -> tuple[str, int]:
    repo, _, number = sample_id.partition("#")
    return repo, int(number) if number.isdigit() else -1


# --- storage ----------------------------------------------------------------------------------

def new_store(described: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "encoder": described, "model_name": described["model_name"],
            "dim": described["dim"], "manifest": manifest["identity"] if manifest else None,
            "sample_ids": [], "embeddings": torch.empty((0, described["dim"])),
            "labels": torch.empty(0, dtype=torch.long), "splits": [], "diff_sha256": [], "num_tokens": [],
            "num_chunks": [], "truncated": [], "fallback_full_diff": []}


_PER_SAMPLE = ("splits", "diff_sha256", "num_tokens", "num_chunks", "truncated", "fallback_full_diff")


def upsert(store: dict[str, Any], sample: dict[str, Any], encoded: Any) -> None:
    """Add a new sample, or replace a stale one in place (its row number is kept)."""
    vector = encoded.vector.reshape(1, -1).float()
    values = {"splits": sample.get("split"), "diff_sha256": sample["diff_sha256"], "num_tokens": encoded.num_tokens,
              "num_chunks": encoded.num_chunks, "truncated": encoded.truncated,
              "fallback_full_diff": encoded.fallback_full_diff}
    store.setdefault("splits", [None] * len(store["sample_ids"]))  # files from schema 1
    if sample["sample_id"] in store["sample_ids"]:
        row = store["sample_ids"].index(sample["sample_id"])
        store["embeddings"][row] = vector[0]
        store["labels"][row] = sample["label"]
        for key, value in values.items():
            store[key][row] = value
        return
    store["sample_ids"].append(sample["sample_id"])
    store["embeddings"] = torch.cat([store["embeddings"], vector])
    store["labels"] = torch.cat([store["labels"], torch.tensor([sample["label"]], dtype=torch.long)])
    for key, value in values.items():
        store[key].append(value)


def reorder(store: dict[str, Any], order: list[str]) -> None:
    """Put rows in manifest order (convenience only; joins must still use sample_id)."""
    position = {sample_id: index for index, sample_id in enumerate(store["sample_ids"])}
    indices = [position[sample_id] for sample_id in order if sample_id in position]
    store["sample_ids"] = [store["sample_ids"][index] for index in indices]
    store["embeddings"] = store["embeddings"][indices]
    store["labels"] = store["labels"][indices]
    for key in _PER_SAMPLE:
        store[key] = [store[key][index] for index in indices]


def load_store(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    # Plain tensors, lists and strings only, so the safe weights_only loader works.
    return torch.load(path, weights_only=True)


def save_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(store, temporary)
    temporary.replace(path)


def write_index(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    splits = store.get("splits") or [None] * len(store["sample_ids"])
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "row", "label", "split", "dim", "num_tokens", "num_chunks", "truncated",
                         "fallback_full_diff", "diff_sha256"])
        for row, sample_id in enumerate(store["sample_ids"]):
            writer.writerow([sample_id, row, int(store["labels"][row]), splits[row] or "", store["dim"],
                             store["num_tokens"][row], store["num_chunks"][row], int(store["truncated"][row]),
                             int(store["fallback_full_diff"][row]), store["diff_sha256"][row]])
    temporary.replace(path)


def _pretrained(model_name: str, settings: EncoderSettings, device: str) -> DiffEncoder:
    return DiffEncoder.from_pretrained(model_name, settings, device)


if __name__ == "__main__":
    raise SystemExit(main())
