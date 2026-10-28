"""Blind developer survey for the RAG explanations (Mandatory 2): build a Google Form, convert its export.

    # 1. build: readable survey + private key + a Google Apps Script that creates the form
    python scripts/rag_v5_google_form.py build --checkpoint data/rag_v5/eval/generation_checkpoint.json

    # 2. paste docs/eval_v5/create_google_form.gs into https://script.google.com, Run, open the logged link

    # 3. convert the form's CSV export (Responses -> Download CSV) for scripts/rag_v5_survey.py
    python scripts/rag_v5_google_form.py convert --export responses.csv --out data/rag_v5/survey_long.csv
    python scripts/rag_v5_survey.py --responses data/rag_v5/survey_long.csv --key data/rag_v5/survey_key.json

Only PRs where all three systems produced an explanation are used, so raters never compare a
real answer with a blank one. The A/B/C order is shuffled per PR with a fixed seed and written to
the private key (same format as rag_v5_survey.py), which respondents never see.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[1]
MODES = ("signature", "text", "none")
ITEMS = ("correct", "useful", "actionable", "clear")
ROWS = ("Correct: matches the evidence", "Useful to a code reviewer", "Actionable fix", "Clear and easy to read")
ROLE_QUESTION = "Which describes you best?"
YEARS_QUESTION = "How many years have you been programming?"
_EDGE = re.compile(r"([^\s;]+) -> ([A-Z_]+) -> ([^\s;]+) \((-?[0-9.]+)\)")


def short_node(node_id: str) -> str:
    """'rich/console.py:rich.console.Console.get_style' -> 'rich.console.Console.get_style'."""
    return node_id.split(":", 1)[-1]


def evidence_text(sample_id: str, summary: str) -> str:
    """Plain-English evidence for raters from the evaluation's evidence summary."""
    repo, number = sample_id.split("#")
    title = re.search(r"PR: (.*?)\. Risk score", summary)
    score = re.search(r"Risk score ([0-9.]+) \(threshold ([0-9.]+)\)", summary)
    lines = [f"Pull request: https://github.com/{repo}/pull/{number}"]
    if title:
        lines.append(f"Title: {title.group(1)}")
    if score:
        risk, threshold = float(score.group(1)), float(score.group(2))
        flagged = "flags it as likely to increase coupling" if risk >= threshold else "does not flag it"
        # 4 decimals: at 3, a score just below the threshold (0.441004 vs 0.441173) read as "0.441 (threshold
        # 0.441), so it does not flag it", which contradicts itself for raters.
        lines.append(f"The model's risk score is {risk:.4f} (threshold {threshold:.4f}), so it {flagged}.")
    edges = _EDGE.findall(summary)[:3]
    if edges:
        lines.append("Dependencies with the most influence on the score (+ pushes risk up, - pushes it down):")
        lines += [f"  - {short_node(a)} {rel} {short_node(b)} ({float(w):+.3f})" for a, rel, b, w in edges]
    return "\n".join(lines)


def fix_text(suggestion) -> str:
    """The suggested fix as plain text (the model returns a JSON object of varying shape)."""
    if not isinstance(suggestion, dict) or not any(suggestion.values()):
        return "Suggested fix: none given."
    parts = []
    if suggestion.get("refactoring"):
        parts.append(f"Suggested fix: {suggestion['refactoring']}")
    files = suggestion.get("files")
    if files:
        parts.append("Files: " + (", ".join(files) if isinstance(files, list) else str(files)))
    steps = suggestion.get("steps")
    if isinstance(steps, list) and steps:
        parts.append("Steps:\n" + "\n".join(f"  {index}. {re.sub(r'^[0-9]+[.)] *', '', str(step))}"
                                             for index, step in enumerate(steps, 1)))
    elif steps:
        parts.append(f"Steps: {steps}")
    sketch = suggestion.get("code_sketch") or suggestion.get("optional_code_sketch")
    if sketch:
        parts.append("Code sketch:\n" + str(sketch).replace("\\n", "\n"))
    return "\n".join(parts) if parts else "Suggested fix: none given."


def build(checkpoint: list[dict], count: int = 12, seed: int = 2026) -> tuple[list[dict], dict]:
    grouped: dict[str, dict] = defaultdict(dict)
    for record in checkpoint:
        grouped[record["sample_id"]][record["mode"]] = record
    complete = sorted(sample_id for sample_id, modes in grouped.items()
                      if all((modes.get(mode, {}).get("answer", {}).get("explanation") or "").strip() for mode in MODES))
    if len(complete) < count:
        raise SystemExit(f"Only {len(complete)} PRs have an answer from all three systems; need {count}")
    rng = random.Random(seed)
    chosen = sorted(rng.sample(complete, count))
    prs, mapping = [], {}
    for sample_id in chosen:
        order = list(MODES)
        rng.shuffle(order)
        mapping[sample_id] = dict(zip("ABC", order))
        modes = grouped[sample_id]
        prs.append({"sample_id": sample_id,
                    "evidence": evidence_text(sample_id, modes["signature"].get("evidence_summary", "")),
                    "explanations": [{"letter": letter,
                                      "text": modes[mode]["answer"]["explanation"].strip() + "\n\n"
                                      + fix_text(modes[mode]["answer"].get("suggestion"))}
                                     for letter, mode in zip("ABC", order)]})
    key = {"seed": seed, "mapping": mapping, "eligible_prs": len(complete),
           "note": "Only PRs where all three systems answered were eligible."}
    return prs, key


def apps_script(prs: list[dict]) -> str:
    data = json.dumps(prs, ensure_ascii=False, indent=1)
    rows = json.dumps(list(ROWS))
    return f"""// Creates the blind explanation survey as a Google Form in your Google account.
// Open https://script.google.com -> New project -> paste this file -> Run createSurvey -> allow access.
// The form's links appear in the execution log. Generated by scripts/rag_v5_google_form.py.
const PRS = {data};
const ROWS = {rows};

function createSurvey() {{
  const form = FormApp.create('Code review explanations: blind developer survey');
  form.setDescription(
    'We are evaluating automatically generated explanations of pull requests (PRs) in open-source Python projects. ' +
    'A model predicts whether a PR will make the touched code more tightly coupled over the next six months; ' +
    'three different systems then explain that prediction. For each of ' + PRS.length + ' PRs you will see the ' +
    'evidence and three explanations (A, B, C, in random order). Rate each one from 1 (very poor) to 5 (excellent). ' +
    'About 15 to 20 minutes. Responses are anonymous and used only for a university project report.');
  form.setCollectEmail(false);
  form.addMultipleChoiceItem().setTitle('{ROLE_QUESTION}').setRequired(true)
      .setChoiceValues(['Professional developer', 'Student', 'Researcher or academic', 'Other']);
  form.addTextItem().setTitle('{YEARS_QUESTION}').setRequired(true)
      .setValidation(FormApp.createTextValidation().requireNumberBetween(0, 60)
                     .setHelpText('Please enter a number').build());
  PRS.forEach(function (pr, index) {{
    form.addPageBreakItem().setTitle('PR ' + (index + 1) + ' of ' + PRS.length);
    form.addSectionHeaderItem().setTitle('Evidence').setHelpText(pr.evidence);
    pr.explanations.forEach(function (explanation) {{
      form.addSectionHeaderItem().setTitle('Explanation ' + explanation.letter).setHelpText(explanation.text);
      form.addGridItem().setTitle('PR ' + (index + 1) + ', explanation ' + explanation.letter)
          .setRows(ROWS).setColumns(['1', '2', '3', '4', '5']).setRequired(true);
    }});
    form.addParagraphTextItem().setTitle('PR ' + (index + 1) + ': optional comment').setRequired(false);
  }});
  Logger.log('Send this link to respondents: ' + form.getPublishedUrl());
  Logger.log('Edit link (keep private): ' + form.getEditUrl());
}}
"""


def readable_markdown(prs: list[dict]) -> str:
    lines = ["# Blind explanation survey (content of the Google Form)", "",
             "Built by scripts/rag_v5_google_form.py. Ratings: 1 (very poor) to 5 (excellent) on: "
             + "; ".join(ROWS) + ".", ""]
    for index, pr in enumerate(prs, 1):
        lines += [f"## PR {index} of {len(prs)}", "", "```", pr["evidence"], "```", ""]
        for explanation in pr["explanations"]:
            lines += [f"### Explanation {explanation['letter']}", "", explanation["text"], ""]
    return "\n".join(lines) + "\n"


def convert(export_path: Path, key: dict, out_path: Path) -> int:
    """Google Forms export (one row per respondent) -> one row per respondent, PR and explanation."""
    order = sorted(key["mapping"])
    with export_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    written = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["respondent_id", "years_coding", "role", "sample_id", "variant", *ITEMS])
        for number, row in enumerate(rows, 1):
            for index, sample_id in enumerate(order, 1):
                for letter in "ABC":
                    title = f"PR {index}, explanation {letter}"
                    ratings = [row.get(f"{title} [{label}]", "").strip() for label in ROWS]
                    if not all(ratings):
                        raise SystemExit(f"Respondent {number}: missing ratings for {title}")
                    writer.writerow([f"r{number:03d}", row[YEARS_QUESTION], row[ROLE_QUESTION], sample_id, letter,
                                     *ratings])
                    written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("build")
    make.add_argument("--checkpoint", type=Path, default=ROOT / "data/rag_v5/eval/generation_checkpoint.json")
    make.add_argument("--key", type=Path, default=ROOT / "data/rag_v5/survey_key.json")
    make.add_argument("--script", type=Path, default=ROOT / "docs/eval_v5/create_google_form.gs")
    make.add_argument("--markdown", type=Path, default=ROOT / "docs/eval_v5/survey_form.md")
    make.add_argument("--count", type=int, default=12)
    change = sub.add_parser("convert")
    change.add_argument("--export", type=Path, required=True)
    change.add_argument("--key", type=Path, default=ROOT / "data/rag_v5/survey_key.json")
    change.add_argument("--out", type=Path, default=ROOT / "data/rag_v5/survey_long.csv")
    args = parser.parse_args(argv)
    if args.command == "build":
        prs, key = build(json.loads(args.checkpoint.read_text(encoding="utf-8")), args.count)
        for path, text in ((args.key, json.dumps(key, indent=2) + "\n"), (args.script, apps_script(prs)),
                           (args.markdown, readable_markdown(prs))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(f"{len(prs)} PRs (of {key['eligible_prs']} with three answers). Private key: {args.key}. "
              f"Form script: {args.script}")
    else:
        key = json.loads(args.key.read_text(encoding="utf-8"))
        print(f"Wrote {convert(args.export, key, args.out)} rating rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
