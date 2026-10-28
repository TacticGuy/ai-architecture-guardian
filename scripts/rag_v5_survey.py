"""Build a blind survey from evaluation results or analyze exported ratings."""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ("correct", "useful", "actionable", "clear")
MODES = ("signature", "text", "none")


def build_form(results: dict, form_path: Path, key_path: Path, seed: int = 2026) -> dict:
    grouped = defaultdict(dict)
    for row in results["per_pr"]:
        grouped[row["sample_id"]][row["mode"]] = row
    complete = sorted(sample_id for sample_id, modes in grouped.items() if set(modes) == set(MODES))
    if not complete:
        raise ValueError("No complete three-mode PRs in evaluation results")
    rng = random.Random(seed)
    chosen = sorted(rng.sample(complete, min(12, len(complete))))
    key = {}
    lines = ["# AI Architecture Guardian: blind explanation survey", "",
             "Copy these questions into a Google Form. Do not show the private key file to respondents.",
             "For each PR, rate each explanation from 1 (very poor) to 5 (excellent) on correctness,",
             "usefulness to a reviewer, actionability of the suggested fix, and clarity.",
             "Also ask for years of coding and whether the respondent is a student or professional.", ""]
    for sample_id in chosen:
        order = list(MODES)
        rng.shuffle(order)
        key[sample_id] = dict(zip("ABC", order))
        row = grouped[sample_id]["signature"]
        lines.extend([f"## PR {sample_id}", f"Evidence summary: {row.get('evidence_summary', '') or 'Read the supplied PR attribution sheet.'}", ""])
        for letter, mode in zip("ABC", order):
            answer = grouped[sample_id][mode]["answer"]
            lines += [f"### Explanation {letter}", answer.get("explanation", "[No grounded answer returned]"),
                      "Suggested fix: " + json.dumps(answer.get("suggestion", {}), ensure_ascii=False),
                      "Rate correctness, usefulness, actionability, and clarity (1-5).", ""]
    lines += ["## Response export format", "",
              "Export one row per respondent, PR, and variant with columns:",
              "respondent_id, years_coding, role, sample_id, variant, correct, useful, actionable, clear."]
    form_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    form_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    key_path.write_text(json.dumps({"seed": seed, "mapping": key}, indent=2) + "\n", encoding="utf-8")
    return key


def _holm(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    available = sorted((p, name) for name, p in pvalues.items() if p is not None)
    adjusted = dict.fromkeys(pvalues)
    maximum = 0.0
    for index, (p, name) in enumerate(available):
        maximum = max(maximum, min(1.0, p * (len(available) - index)))
        adjusted[name] = maximum
    return adjusted


def analyze(csv_path: Path, key_path: Path) -> dict:
    from scipy.stats import friedmanchisquare, wilcoxon
    import krippendorff

    mapping = json.loads(key_path.read_text(encoding="utf-8"))["mapping"]
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            sample_id, variant = row["sample_id"], row["variant"].upper()
            if sample_id not in mapping or variant not in mapping[sample_id]:
                raise ValueError(f"Unknown PR or blinded variant: {sample_id} {variant}")
            mode = mapping[sample_id][variant]
            ratings = {item: int(row[item]) for item in ITEMS}
            if any(not 1 <= value <= 5 for value in ratings.values()):
                raise ValueError("Likert ratings must be integers 1 to 5")
            rows.append({"respondent_id": row["respondent_id"], "sample_id": sample_id,
                         "mode": mode, "years_coding": row["years_coding"], "role": row["role"], **ratings})
    by_mode = {mode: {item: [r[item] for r in rows if r["mode"] == mode] for item in ITEMS} for mode in MODES}
    descriptive = {mode: {item: {"n": len(vals), "mean": statistics.mean(vals) if vals else None,
                                  "median": statistics.median(vals) if vals else None}
                          for item, vals in data.items()} for mode, data in by_mode.items()}
    blocks = defaultdict(dict)
    for row in rows:
        blocks[(row["respondent_id"], row["sample_id"])][row["mode"]] = row
    complete = [value for value in blocks.values() if set(value) == set(MODES)]
    tests = {}
    for item in ITEMS:
        vectors = [[block[mode][item] for block in complete] for mode in MODES]
        if len(complete) < 2 or all(a == b == c for a, b, c in zip(*vectors)):
            tests[item] = {"friedman_p": None, "paired_wilcoxon_p_holm": {}}
            continue
        friedman_p = float(friedmanchisquare(*vectors).pvalue)
        pairs = {}
        for a, b in ((0, 1), (0, 2), (1, 2)):
            key = f"{MODES[a]}_vs_{MODES[b]}"
            pairs[key] = (float(wilcoxon(vectors[a], vectors[b]).pvalue)
                          if any(x != y for x, y in zip(vectors[a], vectors[b])) else None)
        tests[item] = {"friedman_p": friedman_p, "paired_wilcoxon_p_holm": _holm(pairs)}
    # Raters are rows; units are PR-mode pairs. Missing ratings remain NaN.
    raters = sorted({r["respondent_id"] for r in rows})
    units = sorted({(r["sample_id"], r["mode"]) for r in rows})
    lookup = {(r["respondent_id"], r["sample_id"], r["mode"]): r for r in rows}
    alpha = {}
    for item in ITEMS:
        matrix = [[lookup.get((rater, sample, mode), {}).get(item, float("nan"))
                   for sample, mode in units] for rater in raters]
        try:
            alpha[item] = float(krippendorff.alpha(reliability_data=matrix, level_of_measurement="ordinal"))
        except (ValueError, ZeroDivisionError):
            alpha[item] = None
    respondents = {(r["respondent_id"], r["years_coding"], r["role"]) for r in rows}
    return {"respondent_count": len(respondents), "respondents": [
        {"id": rid, "years_coding": years, "role": role} for rid, years, role in sorted(respondents)],
        "rating_rows": len(rows), "complete_paired_blocks": len(complete),
        "descriptive": descriptive, "tests": tests, "krippendorff_alpha_ordinal": alpha}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "data" / "rag_v5" / "eval" / "results.json")
    parser.add_argument("--form", type=Path, default=ROOT / "docs" / "eval_v5" / "survey_form.md")
    parser.add_argument("--key", type=Path, default=ROOT / "data" / "rag_v5" / "survey_key.json")
    parser.add_argument("--responses", type=Path, help="Analyze a real exported CSV instead of building form text")
    parser.add_argument("--analysis-out", type=Path, default=ROOT / "data" / "rag_v5" / "survey_analysis.json")
    args = parser.parse_args()
    if args.responses:
        result = analyze(args.responses, args.key)
        args.analysis_out.parent.mkdir(parents=True, exist_ok=True)
        args.analysis_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Analyzed {result['respondent_count']} real respondents: {args.analysis_out}")
    else:
        results = json.loads(args.results.read_text(encoding="utf-8"))
        mapping = build_form(results, args.form, args.key)
        print(f"Prepared {len(mapping)} PRs: {args.form} (private key: {args.key})")


if __name__ == "__main__":
    main()
