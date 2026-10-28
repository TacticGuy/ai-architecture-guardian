"""Validate the graph's edges against established tools and a hand-labelled gold set (Mandatory 1).

    python scripts/validate_graph_v5.py --pycg-dir ../validation_v5_sources/PyCG \
        --repos-dir ../validation_v5_sources/repos --out data/validation_v5/

Keep the PyCG clone and the repository checkouts OUTSIDE this project: pytest would otherwise
collect (and import) their test files.

  1a CALLS            vs the PyCG micro-benchmark (ground-truth callgraph.json per snippet)
  1b IMPORTS          vs grimp on 10 pinned repositories (see REPOSITORIES in imports_check.py)
  1c CALLS/INHERITS/ACCESSES_GLOBAL vs tests/fixtures/validation_v5/gold.json
Writes results.json (everything, including every disagreement) and results.md (the tables).
--pycg-python points at an interpreter with pycg installed, to add PyCG's own row; without it,
the row quotes the PyCG paper.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation_v5.gold_set import RELATIONS, run_gold_set  # noqa: E402
from src.validation_v5.imports_check import CAUSES, run_imports_check  # noqa: E402
from src.validation_v5.metrics import percent  # noqa: E402
from src.validation_v5.pycg_bench import run_benchmark  # noqa: E402

PYCG_PAPER = {"precision": 0.992, "recall": 0.699,
              "source": "Salis et al., \"PyCG: Practical Call Graph Generation in Python\", ICSE 2021 "
                        "(arXiv:2103.00587), abstract: precision ~99.2%, recall ~69.9%"}
CLASSIFIED = ("pallets/flask", "psf/requests", "pallets/click")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pycg-dir", type=Path, required=True, help="clone of github.com/vitsalis/PyCG")
    parser.add_argument("--repos-dir", type=Path, required=True, help="folder with <owner>__<repo> checkouts")
    parser.add_argument("--out", type=Path, default=ROOT / "data/validation_v5")
    parser.add_argument("--pycg-python", help="python executable with pycg installed (optional)")
    parser.add_argument("--gold", type=Path, default=ROOT / "tests/fixtures/validation_v5/gold.json")
    parser.add_argument("--second", type=Path, default=ROOT / "tests/fixtures/validation_v5/second_labeller.json")
    args = parser.parse_args(argv)

    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]
    snippets = args.pycg_dir / "micro-benchmark" / "snippets"
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pycg_benchmark": run_benchmark(snippets, settings, args.pycg_python),
        "imports_vs_grimp": run_imports_check(args.repos_dir, settings, set(CLASSIFIED)),
        "gold_set": run_gold_set(args.gold, args.repos_dir, settings, args.second),
    }
    if not args.pycg_python:
        results["pycg_benchmark"]["pycg_paper"] = PYCG_PAPER
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (args.out / "results.md").write_text(markdown(results), encoding="utf-8")
    print(markdown(results))
    return 0


def _row(name: str, s: dict, extra: str = "") -> str:
    return (f"| {name} | {percent(s['precision'])} | {percent(s['recall'])} | {percent(s.get('f1'))} | "
            f"{s['tp']} | {s['fp']} | {s['fn']} |{extra}")


def markdown(results: dict) -> str:
    out = ["# Graph validation results (v5)", "", f"Generated {results['generated_at']}.", ""]
    bench = results["pycg_benchmark"]
    ours = bench["ours"]
    out += ["## 1a. CALLS vs the PyCG micro-benchmark", "",
            f"{ours['overall']['snippets']} snippets; micro-averaged; external callees dropped from the "
            "ground truth (our graph has no nodes for them). Percentages.", "",
            "| Category | Precision | Recall | F1 | TP | FP | FN | Snippets |", "|---|---|---|---|---|---|---|---|"]
    for category, s in ours["per_category"].items():
        out.append(_row(category, s, f" {s['snippets']} |"))
    out.append(_row("**overall (ours)**", ours["overall"], f" {ours['overall']['snippets']} |"))
    if "pycg" in bench:
        out.append(_row("PyCG (run here, same conversion)", bench["pycg"]["overall"],
                        f" {bench['pycg']['overall']['snippets']} |"))
    else:
        paper = bench["pycg_paper"]
        out.append(f"| PyCG (paper, not run here) | {percent(paper['precision'])} | {percent(paper['recall'])} "
                   f"| | | | | |")
        out += ["", f"PyCG row: {paper['source']}. The paper's numbers count all callees, including "
                    "external ones, so they are a reference point, not a like-for-like row."]

    imports = results["imports_vs_grimp"]
    out += ["", "## 1b. IMPORTS vs grimp", "",
            "Internal module -> module pairs. \"Shared modules\" leaves out modules grimp does not scan.", "",
            "| Repository | Tag | Precision | Recall | F1 | TP | FP | FN | Shared-modules P / R |",
            "|---|---|---|---|---|---|---|---|---|"]
    for name, row in imports["per_repo"].items():
        if row.get("missing"):
            out.append(f"| {name} | {row['tag']} | not cloned | | | | | | |")
            continue
        shared = row["shared_modules"]
        out.append(_row(f"{name} | {row['tag']}", row,
                        f" {percent(shared['precision'])} / {percent(shared['recall'])} |"))
    out.append(_row("**total** | ", imports["total"], " |"))
    out += ["", "Disagreements by cause (" + ", ".join(CLASSIFIED) + "):", "",
            "| Repository | " + " | ".join(CAUSES) + " |", "|---" * (len(CAUSES) + 1) + "|"]
    for name in CLASSIFIED:
        causes = imports["per_repo"].get(name, {}).get("causes")
        if causes:
            out.append(f"| {name} | " + " | ".join(str(causes[c]) for c in CAUSES) + " |")

    gold = results["gold_set"]
    out += ["", "## 1c. Hand-labelled gold set", "",
            f"{len(gold['files'])} files: " + ", ".join(f"{f['repo']} `{f['path']}`" for f in gold["files"]) + ".", "",
            "| Relation | Precision | Recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    for kind in RELATIONS:
        out.append(_row(kind, gold["per_relation"][kind]))
    out.append(_row("**all three**", gold["overall"]))
    agreement = gold.get("agreement")
    if agreement:
        out.append("")
        if "overall" in agreement:
            out.append(f"Inter-labeller agreement on `{agreement['path']}` (positive specific agreement): "
                       f"{percent(agreement['overall'])}% overall; " + ", ".join(
                           f"{k} {percent(v)}%" for k, v in agreement["per_relation"].items()) + ".")
        else:
            out.append(f"Inter-labeller agreement on `{agreement['path']}`: {agreement['status']}.")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
