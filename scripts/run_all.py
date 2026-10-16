"""Rebuild every output for one data version with one command.

    python scripts/run_all.py --manifest artifacts/gnn_embeddings_v4.json
    python scripts/run_all.py --manifest artifacts/gnn_embeddings_v4.json --from fusion     # continue
    python scripts/run_all.py --manifest artifacts/gnn_embeddings_v4.json --explain-split all --with-eval

Steps (each one is the real script with its own safety checks):
  embeddings  scripts/build_diff_embeddings.py   CodeReviewer vectors (already-encoded diffs are reused)
  fusion      scripts/train_fusion.py            fusion model, baselines, metrics
  explain     scripts/explain_prs.py             XAI layers A, B and C
  kb          scripts/build_kb.py                chatbot knowledge base
  eval        scripts/eval_chatbot.py            retrieval check (free); full Groq run with --with-eval
                                                 (asks every question again when the knowledge base was rebuilt)

Inputs it needs (checked before anything runs): the manifest, the GNN embeddings and checkpoint named
in it (next to the manifest), and data/future_pr_samples_<version>. Use --no-graph to skip layer C.

The run stops at the first failing step and says how to continue from it. Every run is logged
in data/runs/<version>/run.json (steps, exit codes, durations, input file fingerprints).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fusion.data import manifest_version  # noqa: E402

STEPS = ("embeddings", "fusion", "explain", "kb", "eval")


def main(argv: list[str] | None = None, encoder_factory: Callable | None = None, llm_factory: Callable | None = None,
         root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Rebuild embeddings, fusion, XAI, knowledge base and chatbot check.")
    parser.add_argument("--manifest", type=Path, required=True, help="e.g. artifacts/gnn_embeddings_v4.json")
    parser.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0], help="Start at this step")
    parser.add_argument("--to", dest="stop", choices=STEPS, default=STEPS[-1], help="Stop after this step")
    parser.add_argument("--explain-split", choices=("train", "validation", "test", "all"), default="test",
                        help="PRs to explain (default test; 'all' takes longer)")
    parser.add_argument("--no-graph", action="store_true", help="Skip XAI layer C (no GNN checkpoint needed)")
    parser.add_argument("--with-eval", action="store_true", help="Also run the full Groq evaluation (~7 minutes)")
    parser.add_argument("--pause", type=float, default=25.0, help="Seconds between Groq calls in --with-eval")
    parser.add_argument("--diff-model", default="microsoft/codereviewer")
    args = parser.parse_args(argv)
    if STEPS.index(args.start) > STEPS.index(args.stop):
        parser.error("--from comes after --to")

    manifest = args.manifest if args.manifest.is_absolute() else (root / args.manifest)
    version = manifest_version(manifest)
    if version is None:
        parser.error("the manifest name must end in _v<number>, e.g. gnn_embeddings_v4.json")
    paths = _paths(root, manifest, version, args.diff_model)
    selected = STEPS[STEPS.index(args.start): STEPS.index(args.stop) + 1]

    problems = preflight(paths, selected, need_graph=not args.no_graph)
    if problems:
        print("Cannot start, these inputs are missing:")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    commands = _commands(paths, args, selected)
    record: dict[str, Any] = {"version": version, "started": _now(), "steps": [], "inputs": _fingerprints(paths)}
    print(f"run_all {version}: {' -> '.join(selected)}")
    code = 0
    for step in selected:
        argv_step, extra = commands[step]
        if step == "eval" and not paths["questions"].is_file():
            print(f"\n=== {step}: skipped (no question set {paths['questions'].name} for this version)")
            record["steps"].append({"step": step, "status": "skipped", "seconds": 0})
            continue
        print(f"\n=== {step}: python scripts/{_SCRIPTS[step]}.py {' '.join(argv_step)}")
        started = time.perf_counter()
        kwargs = {"encoder_factory": encoder_factory} if step in ("embeddings", "explain") else {}
        if step == "eval":
            kwargs = {"llm_factory": llm_factory, "root": root}
        for extra_argv in extra:
            code = _run(step, argv_step + extra_argv, kwargs)
            if code != 0:
                break
        seconds = round(time.perf_counter() - started, 1)
        record["steps"].append({"step": step, "exit_code": code, "seconds": seconds,
                                "status": "ok" if code == 0 else "failed"})
        if code != 0:
            print(f"\n*** {step} failed (exit code {code}). Fix the problem above, then continue with:\n"
                  f"    python scripts/run_all.py --manifest {args.manifest} --from {step}")
            break
        print(f"=== {step}: ok ({seconds}s)")

    record["finished"] = _now()
    record["result"] = "ok" if code == 0 else "failed"
    _log(paths["runs"] / "run.json", record)
    if code == 0:
        print(f"\nAll done for {version}. Web app: uvicorn api.main:app --port 8000 (+ npm run dev in web/) | "
              f"Chat: python scripts/chat.py --manifest {args.manifest}")
    return code


# --- steps ---------------------------------------------------------------------------------------

_SCRIPTS = {"embeddings": "build_diff_embeddings", "fusion": "train_fusion", "explain": "explain_prs",
            "kb": "build_kb", "eval": "eval_chatbot"}


def _paths(root: Path, manifest: Path, version: str, diff_model: str) -> dict[str, Path]:
    named = _manifest_fields(manifest)
    diff_dir = root / "data/embeddings" / f"{diff_model.replace('/', '__')}__{manifest.stem}"
    return {"manifest": manifest, "samples": root / "data" / f"future_pr_samples_{version}",
            "gnn": manifest.parent / named.get("embedding_file", f"gnn_embeddings_{version}.pt"),
            "checkpoint": manifest.parent / named.get("checkpoint_name", f"gnn_future_risk_{version}.pt"),
            "diff_dir": diff_dir, "diff": diff_dir / "embeddings.pt", "fusion": root / "data/fusion" / version,
            "xai": root / "data/xai" / version, "kb": root / "data/kb" / version,
            "questions": root / "docs/eval" / f"chatbot_questions_{version}.json",
            "docs": (root / "docs/knowledge") if (root / "docs/knowledge").is_dir() else ROOT / "docs/knowledge",
            "eval": root / "data/eval" / version, "runs": root / "data/runs" / version}


def _commands(paths: dict[str, Path], args: Any, selected: tuple[str, ...]) -> dict[str, tuple[list[str], list[list[str]]]]:
    manifest, gnn, diff = str(paths["manifest"]), str(paths["gnn"]), str(paths["diff"])
    explain = ["--manifest", manifest, "--gnn", gnn, "--diff", diff, "--diff-model", args.diff_model,
               "--fusion-model", str(paths["fusion"] / "fusion_model.pt"), "--samples-dir", str(paths["samples"]),
               "--output-dir", str(paths["xai"]), "--split", args.explain_split]
    if args.no_graph:
        explain.append("--no-graph")
    else:
        explain += ["--gnn-checkpoint", str(paths["checkpoint"])]
    evaluate = ["--manifest", manifest, "--questions", str(paths["questions"]), "--output-dir", str(paths["eval"])]
    full_eval = ["--pause", str(args.pause)]
    if "kb" in selected:
        full_eval.append("--fresh")               # saved answers came from the old knowledge base
    return {
        "embeddings": (["--manifest", manifest, "--samples-dir", str(paths["samples"]), "--output-dir",
                        str(paths["diff_dir"]), "--model", args.diff_model], [[]]),
        "fusion": (["--manifest", manifest, "--gnn", gnn, "--diff", diff, "--diff-model", args.diff_model,
                    "--output-dir", str(paths["fusion"])], [[]]),
        "explain": (explain, [[]]),
        "kb": (["--manifest", manifest, "--fusion-dir", str(paths["fusion"]), "--xai-dir", str(paths["xai"]),
                "--samples-dir", str(paths["samples"]), "--docs-dir", str(paths["docs"]),
                "--output-dir", str(paths["kb"])], [[]]),
        # always the free retrieval check; the full Groq run only when asked
        "eval": (evaluate, [["--retrieval-only"]] + ([full_eval] if args.with_eval else [])),
    }


def preflight(paths: dict[str, Path], steps: tuple[str, ...], need_graph: bool) -> list[str]:
    """Inputs the selected steps need before anything runs."""
    problems = []
    if not paths["manifest"].is_file():
        problems.append(f"manifest {paths['manifest']} (from the GNN teammate)")
    needs = {
        "gnn": {"fusion", "explain"}, "samples": {"embeddings", "explain", "kb"},
        "checkpoint": {"explain"} if need_graph else set(),
        "diff": set() if "embeddings" in steps else {"fusion", "explain"},
        "fusion_model": set() if "fusion" in steps else {"explain", "kb"},
        "kb": set() if "kb" in steps else {"eval"},
    }
    targets = {"gnn": paths["gnn"], "samples": paths["samples"], "checkpoint": paths["checkpoint"],
               "diff": paths["diff"], "fusion_model": paths["fusion"] / "fusion_model.pt",
               "kb": paths["kb"] / "cards.jsonl"}
    hints = {"gnn": "GNN embeddings from the GNN teammate", "samples": "unzipped samples (metadata.json, diff.patch, "
             "before/graph.pt per PR)", "checkpoint": "GNN checkpoint from the GNN teammate, or use --no-graph",
             "diff": "run from 'embeddings'", "fusion_model": "run from 'fusion'", "kb": "run from 'kb'"}
    for name, used_by in needs.items():
        if used_by & set(steps) and not targets[name].exists():
            problems.append(f"{targets[name]} ({hints[name]})")
    return problems


def _run(step: str, argv: list[str], kwargs: dict[str, Any]) -> int:
    spec = importlib.util.spec_from_file_location(f"run_all_{step}", ROOT / "scripts" / f"{_SCRIPTS[step]}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return int(module.main(argv, **kwargs) or 0)
    except SystemExit as exc:                     # argparse errors inside a step
        return int(exc.code or 0) if isinstance(exc.code, int) else 2


def _manifest_fields(manifest: Path) -> dict[str, str]:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {key: data[key] for key in ("embedding_file", "checkpoint_name") if isinstance(data.get(key), str)}


def _fingerprints(paths: dict[str, Path]) -> dict[str, str]:
    prints = {}
    for name in ("manifest", "gnn", "checkpoint"):
        path = paths[name]
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            prints[path.name] = digest.hexdigest()
    return prints


def _log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if path.is_file():
        try:
            history = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, json.JSONDecodeError):
            history = []
    history.append(record)
    path.write_text(json.dumps({"runs": history[-50:]}, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
