"""Prepare human evidence sheets or evaluate three RAG modes on real references."""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.rag_v5 import explain_pr
from src.rag_v5.retrieval import load_cards

ROOT = Path(__file__).resolve().parents[1]
MODES = ("signature", "text", "none")


def _catalogue_key(value: object) -> str:
    """Normalize a catalogue id or display title for actionability matching."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def select_test_files(folder: Path, per_class: int = 20, seed: int = 2026) -> list[Path]:
    groups: dict[bool, list[Path]] = {True: [], False: []}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") == "attribution_v5/1" and data.get("split") == "test" and not data.get("_note"):
            groups[bool(data.get("predicted_degrading"))].append(path)
    rng = random.Random(seed)
    return sorted(rng.sample(groups[True], min(per_class, len(groups[True]))) +
                  rng.sample(groups[False], min(per_class, len(groups[False]))))


def prepare_sheets(folder: Path, output: Path) -> list[dict]:
    chosen = select_test_files(folder)
    if not chosen:
        raise ValueError("No real test-split attribution files found; synthetic fixtures are excluded")
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, path in enumerate(chosen, 1):
        data = json.loads(path.read_text(encoding="utf-8"))
        safe_name = f"{index:02d}_{data['sample_id'].replace('/', '__').replace('#', '__')}"
        lines = [f"# {data['sample_id']}", "", f"Title: {data.get('title', '')}",
                 f"Predicted degrading: {data.get('predicted_degrading')}",
                 f"Risk score / threshold: {data.get('risk_score')} / {data.get('threshold')}",
                 f"GitHub PR: https://github.com/{data['repo']}/pull/{data['sample_id'].split('#')[-1]}",
                 "", "## Top edges"]
        lines.extend(f"- {e.get('source')} -> {e.get('relation')} -> {e.get('target')} "
                     f"(attribution {e.get('attribution')}; added={e.get('added_in_pr')})"
                     for e in data.get("top_edges", [])[:12])
        lines += ["", "## Touched module coupling"]
        lines.extend(f"- {name}: {json.dumps(info, sort_keys=True)}"
                     for name, info in sorted(data.get("module_evidence", {}).items())
                     if name in data.get("touched_modules", []))
        lines += ["", "## Diff hunks"]
        lines.extend(f"- {h.get('file')}: {json.dumps(h.get('snippet', []))}" for h in data.get("top_hunks", [])[:3])
        lines += ["", "## Human reference (fill after checking GitHub diff)",
                  "Explanation: [write by hand]", "Minimal fix: [write by hand]",
                  "Relevant principle IDs: [choose by hand]", ""]
        (output / f"{safe_name}.md").write_text("\n".join(lines), encoding="utf-8")
        entries.append({"sample_id": data["sample_id"], "attribution_path": str(path.resolve()),
                        "reference_explanation": "", "reference_fix": "", "relevant_principles": []})
    return entries


def bootstrap(values: list[float], seed: int = 2026, repetitions: int = 1000) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0}
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(repetitions))
    return {"mean": statistics.mean(values), "low": means[24], "high": means[975]}


def _paired_wilcoxon(left: list[float], right: list[float]) -> float | None:
    from scipy.stats import wilcoxon
    if len(left) != len(right) or not left or all(a == b for a, b in zip(left, right)):
        return None
    return float(wilcoxon(left, right, zero_method="wilcox").pvalue)


def evaluate(references: list[dict], output: Path) -> dict:
    from bert_score import score as bert_score
    from rouge_score.rouge_scorer import RougeScorer

    if not references or any(not item.get("reference_explanation") or not item.get("reference_fix")
                             for item in references):
        raise ValueError("Fill all hand-written references before evaluating; no synthetic or blank answers")
    cards = load_cards()
    catalogue = {_catalogue_key(value) for c in cards if c["kind"] == "refactoring"
                 for value in (c["id"], c["title"])}
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "generation_checkpoint.json"
    records = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else []
    completed = {(record["sample_id"], record["mode"]) for record in records}
    for item in references:
        data = json.loads(Path(item["attribution_path"]).read_text(encoding="utf-8"))
        if data.get("_note") or data.get("split") != "test":
            raise ValueError(f"Not a real test-split sample: {item['sample_id']}")
        for mode in MODES:
            if (item["sample_id"], mode) in completed:
                continue
            answer = explain_pr(data, mode=mode)
            principles = {c["id"] for c in answer.get("retrieved_cards", [])}
            relevant = set(item.get("relevant_principles") or [])
            suggestion = answer.get("suggestion") or {}
            valid_file = bool(set(suggestion.get("files") or []) & set(data.get("changed_files") or []))
            actionability = bool(valid_file and _catalogue_key(suggestion.get("refactoring", "")) in catalogue)
            records.append({"sample_id": item["sample_id"], "mode": mode, "answer": answer,
                            "reference": item["reference_explanation"],
                            "evidence_summary": (
                                f"PR: {data.get('title', '')}. Risk score {data.get('risk_score')} "
                                f"(threshold {data.get('threshold')}). Strongest graph edges: " +
                                "; ".join(f"{e.get('source')} -> {e.get('relation')} -> {e.get('target')} "
                                          f"({e.get('attribution')})"
                                          for e in data.get("top_edges", [])[:3])
                            ),
                            "precision_at_3": len(principles & relevant) / len(principles) if principles else 0,
                            "recall_at_3": len(principles & relevant) / len(relevant) if relevant else 0,
                            "grounded": not answer.get("grounding_violations") and answer.get("status") != "grounding_failed",
                            "violations": len(answer.get("grounding_violations") or []),
                            "actionable_fix": actionability})
            checkpoint.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Recompute derived actionability when resuming an older checkpoint. This lets
    # scorer fixes apply without making any additional LLM calls.
    attribution_by_id = {item["sample_id"]: json.loads(Path(item["attribution_path"]).read_text(encoding="utf-8"))
                         for item in references}
    for record in records:
        suggestion = record["answer"].get("suggestion") or {}
        data = attribution_by_id[record["sample_id"]]
        valid_file = isinstance(suggestion, dict) and bool(
            set(suggestion.get("files") or []) & set(data.get("changed_files") or []))
        record["actionable_fix"] = bool(
            valid_file and _catalogue_key(suggestion.get("refactoring", "")) in catalogue)
    candidates = [r["answer"].get("explanation", "") for r in records]
    refs = [r["reference"] for r in records]
    p, recall, f1 = bert_score(candidates, refs, model_type="roberta-large", lang="en",
                                rescale_with_baseline=True, verbose=False)
    scorer = RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    for index, record in enumerate(records):
        record.update({"bertscore_p": float(p[index]), "bertscore_r": float(recall[index]),
                       "bertscore_f1": float(f1[index])})
        rouge = scorer.score(refs[index], candidates[index])
        record.update({f"{key}_f1": value.fmeasure for key, value in rouge.items()})
    metrics = ("bertscore_p", "bertscore_r", "bertscore_f1", "rouge1_f1", "rouge2_f1", "rougeL_f1",
               "precision_at_3", "recall_at_3", "grounded", "violations", "actionable_fix")
    summary = {mode: {metric: bootstrap([float(r[metric]) for r in records if r["mode"] == mode])
                      for metric in metrics} for mode in MODES}
    paired = {}
    for competitor in ("text", "none"):
        for metric in ("bertscore_f1", "rougeL_f1"):
            paired[f"signature_vs_{competitor}_{metric}"] = _paired_wilcoxon(
                [r[metric] for r in records if r["mode"] == "signature"],
                [r[metric] for r in records if r["mode"] == competitor])
    result = {"n_prs": len(references), "metrics": summary, "wilcoxon_p": paired, "per_pr": records,
              "limitations": "Model outputs and reference answers need human interpretation; score is not calibrated probability."}
    (output / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# RAG v5 evaluation ({len(references)} real test PRs)", "", "| Metric | Signature | Text | None |",
             "|---|---:|---:|---:|"]
    for metric in metrics:
        vals = [summary[mode][metric] for mode in MODES]
        cells = [f"{v['mean']:.3f} [{v['low']:.3f}, {v['high']:.3f}]" for v in vals]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines += ["", "Paired Wilcoxon p-values: " + json.dumps(paired, sort_keys=True), "",
              "Intervals are 1,000-resample percentile bootstrap intervals. No survey responses are included here."]
    (output / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(MODES, [summary[mode]["bertscore_f1"]["mean"] for mode in MODES])
    ax.set_ylabel("Mean BERTScore F1")
    ax.set_title(f"Explanation quality across {len(references)} test PRs")
    fig.tight_layout()
    fig.savefig(output / "bertscore_f1.png", dpi=170)
    plt.close(fig)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-sheets", action="store_true")
    parser.add_argument("--attributions", type=Path, default=ROOT / "data" / "xai_v5")
    parser.add_argument("--references", type=Path, default=ROOT / "docs" / "eval_v5" / "references.json")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "rag_v5" / "eval")
    args = parser.parse_args()
    try:
        if args.prepare_sheets:
            entries = prepare_sheets(args.attributions, ROOT / "docs" / "eval_v5" / "sheets")
            draft = ROOT / "docs" / "eval_v5" / "references_draft.json"
            draft.write_text(json.dumps({"items": entries}, indent=2) + "\n", encoding="utf-8")
            print(f"Prepared {len(entries)} sheets and {draft}")
        else:
            references = json.loads(args.references.read_text(encoding="utf-8"))["items"]
            result = evaluate(references, args.out)
            print(f"Evaluated {result['n_prs']} PRs; see {args.out}")
    except ValueError as exc:
        parser.exit(2, f"Cannot evaluate yet: {exc}\n")


if __name__ == "__main__":
    main()
