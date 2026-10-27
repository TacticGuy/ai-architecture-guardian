"""SonarQube baseline in batch mode: many PRs per project, one folder per PR (Mandatory 3).

    python scripts/sonar_v5.py --manifest data/v5_manifest.jsonl --repos-dir data/repositories
    python scripts/sonar_v5.py --splits test --max-batches 1      # time one batch first

Per batch of PRs (default 500): every PR's touched production files go into
sonar_before/<owner>__<repo>__<number>/<path> (at before_commit_sha) and
sonar_after/<...>/<path> (at merge_commit_sha). Each side is one scan and one project, with
duplication off (-Dsonar.cpd.exclusions=**/*). Per-PR numbers are summed from the file-level
measures under each PR folder. Both projects are deleted after reading.
Splits run in order (default: test, then val, then train). PRs already in the output are skipped.
Writes data/sonar_v5.jsonl (one line per sample_id, sonar.* numbers or null) and data/sonar_v5.meta.json.
Needs docker/sonarqube running and SONAR_TOKEN in .env.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation_v5.sonar import (  # noqa: E402
    BATCH_SCANNER_ARGS, SCANNER_IMAGE, SonarClient, SonarError, batch_rows, scan_batch_side,
)
from src.validation_v5.tool_metrics import compact, load_rows, read_side  # noqa: E402


def repository_path(repos_dir: Path, repo: str) -> Path | None:
    owner, name = repo.split("/", 1)
    for candidate in (repos_dir / owner / name, repos_dir / f"{owner}__{name}"):
        if (candidate / ".git").exists() or (candidate / "HEAD").is_file():
            return candidate
    return None


def make_batches(samples: list[dict], splits: list[str], size: int) -> list[tuple[str, list[dict]]]:
    """Batches of at most ``size`` PRs, split by split in the given order (never mixing splits)."""
    batches = []
    for split in splits:
        members = sorted((s for s in samples if s.get("split") == split), key=lambda s: s["sample_id"])
        batches += [(split, members[i:i + size]) for i in range(0, len(members), size)]
    return batches


def run_batch(index: int, batch: list[dict], repos_dir: Path, client: SonarClient, host_url: str,
              token: str, scanner=None) -> list[dict]:
    before, after = {}, {}
    for sample in batch:
        repository = repository_path(repos_dir, sample["repo"])
        if repository is None:
            raise SonarError(f"repository not found for {sample['sample_id']}")
        paths = sample["changed_python_files"]
        before[sample["sample_id"]] = read_side(repository, sample["before_commit_sha"], paths)
        after[sample["sample_id"]] = read_side(repository, sample["merge_commit_sha"], paths)
    kwargs = {"scanner": scanner} if scanner else {}
    old = scan_batch_side(before, f"v5_batch_{index}_before", client, host_url, token, **kwargs)
    new = scan_batch_side(after, f"v5_batch_{index}_after", client, host_url, token, **kwargs)
    return batch_rows([s["sample_id"] for s in batch], old, new)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/v5_manifest.jsonl")
    parser.add_argument("--repos-dir", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--out", type=Path, default=ROOT / "data/sonar_v5.jsonl")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--splits", default="test,val,train", help="comma list, run in this order")
    parser.add_argument("--max-batches", type=int, help="stop after N batches (timing runs)")
    parser.add_argument("--sonar-url", default=os.getenv("SONAR_HOST_URL", "http://localhost:9000"))
    parser.add_argument("--scanner-host-url", default=os.getenv("SONAR_SCANNER_HOST_URL", "http://host.docker.internal:9000"),
                        help="the server URL as seen from inside the scanner container")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    token = os.getenv("SONAR_TOKEN")
    if not token:
        raise SystemExit("SONAR_TOKEN is not set (put it in .env; see docker/sonarqube/README.md)")

    samples = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set(load_rows(args.out))
    todo = [s for s in samples if s["sample_id"] not in done]
    batches = make_batches(todo, splits, args.batch_size)[: args.max_batches]
    meta_path = args.out.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {"batches": []}
    client = SonarClient(args.sonar_url, token)
    meta.update(server_version=client.server_version(), scanner_image=SCANNER_IMAGE, batch_size=args.batch_size,
                scanner_args=list(BATCH_SCANNER_ARGS), metrics="sum over each PR's touched files; delta = after - before")
    print(f"{len(done)} PRs already done, {len(batches)} batches to run", file=sys.stderr)

    for number, (split, batch) in enumerate(batches, 1):
        index = len(meta["batches"]) + 1
        started = time.monotonic()
        try:
            rows = run_batch(index, batch, args.repos_dir, client, args.scanner_host_url, token)
        except (SonarError, OSError) as exc:
            print(f"batch {index} ({split}, {len(batch)} PRs) failed: {exc}", file=sys.stderr)
            meta["batches"].append({"index": index, "split": split, "prs": len(batch), "error": str(exc)[:300]})
            _write_meta(meta_path, meta, args.out)
            continue
        with args.out.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(row) + "\n" for row in rows)
        seconds = round(time.monotonic() - started, 1)
        nulls = sum(row["sonar.code_smells"] is None for row in rows)
        meta["batches"].append({"index": index, "split": split, "prs": len(batch), "seconds": seconds,
                                "null_rows": nulls, "finished_at": datetime.now(timezone.utc).isoformat()})
        _write_meta(meta_path, meta, args.out)
        print(f"batch {number}/{len(batches)}: {split}, {len(batch)} PRs, {seconds}s, {nulls} null rows", file=sys.stderr)
    _write_meta(meta_path, meta, args.out)
    return 0


def _write_meta(path: Path, meta: dict, out: Path) -> None:
    rows = load_rows(out) if out.is_file() else {}
    if out.is_file():
        compact(out)
    meta["rows"] = len(rows)
    meta["rows_with_values"] = sum(row.get("sonar.code_smells") is not None for row in rows.values())
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
