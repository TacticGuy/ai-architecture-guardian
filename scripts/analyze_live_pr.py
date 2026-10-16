"""Analyse one public GitHub PR with the already-trained V4 models."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.live_pr import LivePRError, analyze_live_pr  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score one public GitHub PR with the trained V4 pipeline.")
    parser.add_argument("--url", required=True, help="https://github.com/OWNER/REPO/pull/NUMBER")
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts/gnn_embeddings_v4.json")
    parser.add_argument("--repo-path", type=Path, help="Optional existing normal clone (saves download time)")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/live")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--max-hunks", type=int, default=0,
                        help="Explain up to N largest diff hunks (slower; default 0)")
    args = parser.parse_args(argv)
    if args.max_hunks < 0:
        parser.error("--max-hunks must be >= 0")
    try:
        report, result_path = analyze_live_pr(
            args.url, ROOT, manifest_path=args.manifest, output_root=args.output_dir,
            repository_path=args.repo_path, token=os.getenv("GITHUB_TOKEN"),
            device=args.device, max_hunks=args.max_hunks,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        print(f"Saved: {result_path}")
        return 0
    except (LivePRError, OSError, ValueError, RuntimeError) as exc:
        print(f"Live PR analysis failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
