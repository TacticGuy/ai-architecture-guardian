"""Build resumable before/after graph samples from scraped pull requests."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.builder import build_pr_sample
from src.storage.jsonl import JSONLFormatError, iter_jsonl
from src.utils.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build labelled before/after PyG samples from scraped PR metadata."
    )
    parser.add_argument("--repo", required=True, help="Repository identifier, e.g. psf/requests")
    parser.add_argument("--max-samples", type=int, help="Maximum unbuilt PRs to attempt")
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs.jsonl")
    parser.add_argument("--repository-path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/pr_samples")
    args = parser.parse_args(argv)
    if args.max_samples is not None and args.max_samples <= 0:
        parser.error("--max-samples must be positive")

    repository_path = args.repository_path or ROOT / "data/repositories" / Path(*args.repo.split("/"))
    if not repository_path.is_dir() or not (repository_path / ".git").exists():
        print(f"Repository clone not found: {repository_path}")
        print(f"Run: python scripts/clone_repositories.py --repo {args.repo}")
        return 2
    if not args.raw.is_file():
        print(f"Raw PR metadata not found: {args.raw}")
        return 2

    try:
        records = [record for record in iter_jsonl(args.raw) if record.get("repo") == args.repo]
    except JSONLFormatError as exc:
        print(f"Could not read raw PR metadata: {exc}")
        return 2
    if not records:
        print(f"No scraped PRs found for {args.repo}")
        return 2

    settings = load_settings(ROOT / "config/settings.json")
    analysis_settings = settings["static_analysis"]
    built = skipped = 0
    failures: list[dict[str, Any]] = []
    attempted = 0
    for pr in records:
        number = pr.get("pr_number")
        sample_dir = args.output_dir / args.repo.replace("/", "__") / str(number)
        if (sample_dir / "metadata.json").is_file():
            skipped += 1
            print(f"Skipped existing: {args.repo}#{number}")
            continue
        if args.max_samples is not None and attempted >= args.max_samples:
            break
        attempted += 1
        try:
            metadata = build_pr_sample(pr, repository_path, args.output_dir, analysis_settings)
            built += 1
            print(f"Built: {metadata['sample_id']} label={metadata['label']}")
        except Exception as exc:  # One malformed historical PR must not abort the batch.
            failure = {"pr_id": pr.get("pr_id"), "error_type": type(exc).__name__, "error": str(exc)}
            failures.append(failure)
            print(f"Failed: {pr.get('pr_id')} ({type(exc).__name__}: {exc})")

    summary = {
        "schema_version": 1,
        "repo": args.repo,
        "attempted": attempted,
        "built": built,
        "skipped": skipped,
        "failed": len(failures),
        "failures": failures,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_summary(args.output_dir / args.repo.replace("/", "__") / "last_run.json", summary)
    print(f"Summary: attempted={attempted} built={built} skipped={skipped} failed={len(failures)}")
    return 0 if not failures else 1


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
