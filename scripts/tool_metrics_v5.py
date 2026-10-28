"""Run radon / pylint / CodeScene-style hotspot (and SonarQube) on every manifest PR (Mandatory 3).

    # radon + pylint + hotspot on every PR (parallel, resumable)
    python scripts/tool_metrics_v5.py --manifest data/v5_manifest.jsonl --repos-dir data/repositories

    # SonarQube on the test split (needs docker/sonarqube running and SONAR_TOKEN in .env);
    # time it on 10 PRs first, then run a seeded subset if the whole split does not fit
    python scripts/tool_metrics_v5.py --tools sonar --sonar-time 10
    python scripts/tool_metrics_v5.py --tools sonar --sonar-limit 400 --sonar-seed 0

Writes data/tool_metrics_v5.jsonl (one line per sample, "tool.metric" keys, numbers or null)
and data/tool_metrics_v5.meta.json (tool versions, run date, counts, SonarQube subset).
Samples whose tool keys are already in the output are skipped, so an interrupted run resumes.
Repositories are found as <repos-dir>/<owner>/<name> or <repos-dir>/<owner>__<name>.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation_v5.sonar import SCANNER_IMAGE, SonarClient, SonarError, select_sonar_samples, sonar_metrics  # noqa: E402
from src.validation_v5.tool_metrics import (  # noqa: E402
    HOTSPOT_WINDOW_DAYS, compact, done, load_rows, measure_sample, read_side,
)

LOCAL_TOOLS = ("radon", "pylint", "hotspot")


def repository_path(repos_dir: Path, repo: str) -> Path | None:
    owner, name = repo.split("/", 1)
    for candidate in (repos_dir / owner / name, repos_dir / f"{owner}__{name}"):
        if (candidate / ".git").exists() or (candidate / "HEAD").is_file():
            return candidate
    return None


def load_manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/v5_manifest.jsonl")
    parser.add_argument("--repos-dir", type=Path, default=ROOT / "data/repositories")
    parser.add_argument("--out", type=Path, default=ROOT / "data/tool_metrics_v5.jsonl")
    parser.add_argument("--tools", default=",".join(LOCAL_TOOLS), help="comma list of radon,pylint,hotspot,sonar")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--limit", type=int, help="only the first N manifest rows (dev runs)")
    parser.add_argument("--sonar-url", default=os.getenv("SONAR_HOST_URL", "http://localhost:9000"))
    parser.add_argument("--scanner-host-url", default=os.getenv("SONAR_SCANNER_HOST_URL", "http://host.docker.internal:9000"),
                        help="the server URL as seen from inside the scanner container")
    parser.add_argument("--sonar-limit", type=int, help="seeded random subset of the test split")
    parser.add_argument("--sonar-seed", type=int, default=0)
    parser.add_argument("--sonar-time", type=int, help="scan N test PRs, print seconds per PR, write nothing")
    args = parser.parse_args(argv)
    _load_dotenv()

    tools = {tool.strip() for tool in args.tools.split(",") if tool.strip()}
    unknown = tools - {*LOCAL_TOOLS, "sonar"}
    if unknown:
        parser.error(f"unknown tools: {', '.join(sorted(unknown))}")
    samples = load_manifest(args.manifest)[: args.limit]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing = load_rows(args.out)
    meta_path = args.out.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}

    local = tools & set(LOCAL_TOOLS)
    if local:
        run_local(samples, local, args, existing)
        meta["local"] = {"tools": sorted(local), "run_at": _now(), "manifest": str(args.manifest),
                         "hotspot_window_days": HOTSPOT_WINDOW_DAYS, "versions": local_versions()}
    if "sonar" in tools:
        result = run_sonar(samples, args, existing)
        if result is None:
            return 0
        meta["sonar"] = result
    rows = compact(args.out) if args.out.is_file() else 0
    final = load_rows(args.out)
    meta["rows"] = rows
    meta["rows_with"] = {tool: sum(done(row, tool) for row in final.values())
                         for tool in (*LOCAL_TOOLS, "sonar")}
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": rows, "rows_with": meta["rows_with"]}))
    return 0


def run_local(samples: list[dict], tools: set[str], args, existing: dict) -> None:
    todo = [s for s in samples if not all(done(existing.get(s["sample_id"]), tool) for tool in tools)]
    missing = sorted({s["repo"] for s in todo if repository_path(args.repos_dir, s["repo"]) is None})
    if missing:
        print(f"skipped, repository not found under {args.repos_dir}: {', '.join(missing)}", file=sys.stderr)
    todo = [s for s in todo if s["repo"] not in missing]
    print(f"{len(samples) - len(todo)} samples already done or skipped, {len(todo)} to measure", file=sys.stderr)
    started = time.monotonic()
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(measure_sample, repository_path(args.repos_dir, s["repo"]), s,
                               {t for t in tools if not done(existing.get(s["sample_id"]), t)}): s for s in todo}
        for count, future in enumerate(as_completed(futures), 1):
            sample = futures[future]
            try:
                append(args.out, future.result())
            except Exception as exc:  # one broken PR must not stop a 6,000-PR run
                print(f"{sample['sample_id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if count % 50 == 0 or count == len(todo):
                rate = (time.monotonic() - started) / count
                print(f"{count}/{len(todo)} ({rate:.1f}s per PR)", file=sys.stderr)


def run_sonar(samples: list[dict], args, existing: dict) -> dict | None:
    token = os.getenv("SONAR_TOKEN")
    if not token:
        raise SystemExit("SONAR_TOKEN is not set (put it in .env; see docker/sonarqube/README.md)")
    client = SonarClient(args.sonar_url, token)
    version = client.server_version()
    chosen = select_sonar_samples(samples, args.sonar_limit, args.sonar_seed)
    if args.sonar_time:
        chosen = chosen[: args.sonar_time]
    todo = [s for s in chosen if not done(existing.get(s["sample_id"]), "sonar")]
    started, scanned = time.monotonic(), 0
    for sample in todo:
        repository = repository_path(args.repos_dir, sample["repo"])
        if repository is None:
            print(f"{sample['sample_id']}: repository not found", file=sys.stderr)
            continue
        paths = sample["changed_python_files"]
        try:
            row = sonar_metrics(sample["sample_id"], read_side(repository, sample["before_commit_sha"], paths),
                                read_side(repository, sample["merge_commit_sha"], paths), client,
                                args.scanner_host_url, token)
        except (SonarError, subprocess.TimeoutExpired, OSError) as exc:
            print(f"{sample['sample_id']}: {exc}", file=sys.stderr)
            row = {"sonar.code_smells": None, "sonar.cognitive_complexity": None, "sonar.sqale_index": None,
                   "sonar.delta_code_smells": None, "sonar.delta_cognitive_complexity": None,
                   "sonar.delta_sqale_index": None, "sonar.duplicated_lines_density": None}
        scanned += 1
        if not args.sonar_time:
            append(args.out, {"sample_id": sample["sample_id"], **row})
        print(f"sonar {scanned}/{len(todo)} ({(time.monotonic() - started) / scanned:.1f}s per PR)", file=sys.stderr)
    if args.sonar_time:
        per_pr = (time.monotonic() - started) / max(scanned, 1)
        test = sum(s.get("split") == "test" for s in samples)
        print(f"{per_pr:.1f}s per PR; the {test} test PRs would take {per_pr * test / 3600:.1f} h")
        return None
    test_count = sum(s.get("split") == "test" for s in samples)
    return {"run_at": _now(), "server_version": version, "scanner_image": SCANNER_IMAGE,
            "test_split_prs": test_count, "selected": len(chosen),
            "subset": None if len(chosen) == test_count else {"seed": args.sonar_seed, "limit": args.sonar_limit}}


def local_versions() -> dict:
    import radon
    pylint = subprocess.run([sys.executable, "-m", "pylint", "--version"], capture_output=True, text=True).stdout
    git = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    return {"radon": radon.__version__, "pylint": pylint.splitlines()[0] if pylint else None, "git": git,
            "python": sys.version.split()[0]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


if __name__ == "__main__":
    raise SystemExit(main())
