"""Generate one v5 explanation: python scripts/rag_v5_explain.py --help."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.rag_v5 import explain_pr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attribution", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=["signature", "text", "none"], default="signature")
    args = parser.parse_args()
    data = json.loads(args.attribution.read_text(encoding="utf-8"))
    result = explain_pr(data, mode=args.mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.out)
    if result.get("status") == "grounding_failed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
