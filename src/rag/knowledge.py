"""Build the chatbot's knowledge base: short text "cards" made only from real project outputs.

Card kinds
  pr           one per PR in the manifest: label + label evidence, fusion scores, and the
               XAI explanation (layers A, B, C) when that PR has been explained
  predictions  one table per split: every PR's label, fusion score and decision
  model        fusion results for all four models, ranges and warnings (metrics.json)
  dataset      split sizes, class counts, purged PRs, cutoffs
  doc          one per "## " section of the markdown files in docs/knowledge/

Every number in a card is copied from an output file; nothing is estimated. The same
inputs always produce the same cards (no timestamps inside cards).
"""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SPLITS = ("train", "validation", "test")


class KnowledgeError(ValueError):
    """Inputs disagree with each other; building cards from them would mislead."""


@dataclass
class Card:
    id: str
    kind: str
    title: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}"


# --- loading and cross-checking the inputs ---------------------------------------------------

def load_inputs(*, manifest_path: Path, fusion_dir: Path, xai_dir: Path | None, samples_dir: Path | None,
                gnn_metrics_path: Path | None) -> dict[str, Any]:
    manifest_raw = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_raw)
    rows = {row["sample_id"]: row for row in manifest["rows"]}
    metrics = json.loads((fusion_dir / "metrics.json").read_text(encoding="utf-8"))
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    if metrics.get("sources", {}).get("manifest", {}).get("sha256") != manifest_sha:
        raise KnowledgeError("the fusion results were made from a different manifest; re-run train_fusion.py")
    with (fusion_dir / "predictions.csv").open(encoding="utf-8") as handle:
        predictions = {row["sample_id"]: row for row in csv.DictReader(handle)}
    if set(predictions) != set(rows):
        raise KnowledgeError("predictions.csv does not cover exactly the manifest's PRs")
    for sample_id, row in predictions.items():
        if int(row["label"]) != rows[sample_id]["label"] or row["split"] != rows[sample_id]["split"]:
            raise KnowledgeError(f"{sample_id}: label/split in predictions.csv differs from the manifest")

    explanations: dict[str, dict[str, Any]] = {}
    if xai_dir is not None and xai_dir.is_dir():
        for path in sorted(xai_dir.glob("*.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            sample_id = report.get("sample_id")
            if sample_id not in rows:
                raise KnowledgeError(f"{path.name} explains {sample_id}, which is not in the manifest")
            if report["label"] != rows[sample_id]["label"]:
                raise KnowledgeError(f"{path.name}: label differs from the manifest")
            if abs(report["probability"] - float(predictions[sample_id]["p_fusion"])) > 1e-5:
                raise KnowledgeError(f"{path.name}: risk score differs from predictions.csv; "
                                     "re-run explain_prs.py after train_fusion.py")
            explanations[sample_id] = report

    metadata: dict[str, dict[str, Any]] = {}
    in_folder: set[str] = set()
    if samples_dir is not None and samples_dir.is_dir():
        for path in sorted(samples_dir.glob("*/*/metadata.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record.get("sample_id"), str):
                in_folder.add(record["sample_id"])
                if record["sample_id"] in rows:
                    metadata[record["sample_id"]] = record
    gnn_metrics = None
    if gnn_metrics_path is not None and gnn_metrics_path.is_file():
        gnn_metrics = json.loads(gnn_metrics_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "rows": rows, "metrics": metrics, "predictions": predictions,
            "explanations": explanations, "metadata": metadata, "purged": sorted(in_folder - set(rows), key=_pr_order),
            "gnn_metrics": gnn_metrics, "threshold": metrics["results"]["fusion"]["threshold"]}


def _pr_order(sample_id: str) -> tuple[str, int]:
    repo, _, number = sample_id.partition("#")
    return repo, int(number) if number.isdigit() else -1


# --- cards -----------------------------------------------------------------------------------

def build_cards(inputs: dict[str, Any], docs_dir: Path | None) -> list[Card]:
    cards = [dataset_card(inputs), model_card(inputs)]
    cards += [predictions_card(inputs, split) for split in SPLITS]
    cards += [pr_card(inputs, sample_id) for sample_id in inputs["rows"]]
    if docs_dir is not None and docs_dir.is_dir():
        cards += doc_cards(docs_dir)
    ids = [card.id for card in cards]
    duplicates = sorted(card_id for card_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise KnowledgeError(f"duplicate card ids: {duplicates}")
    return cards


def pr_card(inputs: dict[str, Any], sample_id: str) -> Card:
    row, prediction = inputs["rows"][sample_id], inputs["predictions"][sample_id]
    meta = inputs["metadata"].get(sample_id, {})
    threshold = inputs["threshold"]
    probability = float(prediction["p_fusion"])
    predicted = probability >= threshold
    correct = int(predicted) == row["label"]
    lines = [f"PR {sample_id} ({row['split']} split{', merged ' + meta['merged_at'][:10] if meta.get('merged_at') else ''})."]
    if row["label"] == 1:
        evidence = meta.get("event_evidence") or {}
        trigger = meta.get("triggering_refactor_pr")
        when = (meta.get("triggering_refactor_merged_at") or "")[:10]
        files = ", ".join(meta.get("matched_python_files") or [])
        lines.append(f"True label: 1 (risky)." + (f" Reviewed architecture refactor {trigger}"
                                                  f"{' merged ' + when if when else ''} later changed the same files"
                                                  f"{': ' + files if files else ''}." if trigger else ""))
        if evidence.get("rationale"):
            lines.append(f"Reviewer rationale: {evidence['rationale']}")
    else:
        lines.append("True label: 0 (safe). No reviewed architecture refactor touched its files within "
                     f"{meta.get('horizon_months', 6)} months.")
    if meta.get("changed_python_files"):
        lines.append(f"Changed Python files: {', '.join(meta['changed_python_files'])}.")
    lines.append(f"Fusion risk score {fmt(probability)} (threshold {fmt(threshold)}): predicted "
                 f"{'risky' if predicted else 'not risky'}, which is {'correct' if correct else 'wrong'}.")
    lines.append(f"Other models: GNN only {fmt(float(prediction['p_gnn_only']))}, "
                 f"CodeReviewer only {fmt(float(prediction['p_codereviewer_only']))}.")

    report = inputs["explanations"].get(sample_id)
    if report is None:
        lines.append("This PR has not been explained yet (run explain_prs.py with --split all to add it).")
    else:
        parts = report["contributions"]
        lines.append(f"Layer A (logit units): base {signed(parts['base_logit'])}, structure from the GNN "
                     f"{signed(parts['structure_gnn'])}, diff from CodeReviewer {signed(parts['diff_codereviewer'])}.")
        hunks = report.get("hunks", [])[:3]
        if hunks:
            described = [f"{hunk['file']} lines {hunk['new_lines'][0]}-{hunk['new_lines'][1]} "
                         f"(effect {signed(hunk['effect_on_risk'], 3)}; +{hunk['added']}/-{hunk['removed']} lines)"
                         for hunk in hunks]
            lines.append("Layer B, diff hunks with the largest effect on risk: " + "; ".join(described) + ".")
            snippet = " | ".join(hunks[0].get("snippet", [])[:4])
            if snippet:
                lines.append(f"Top hunk code: {snippet}")
        graph = report.get("graph")
        if graph:
            files = [f"{row['file']} {signed(row['attribution'])} ({'touched' if row['touched'] else 'not touched'})"
                     for row in graph["files"][:5]]
            lines.append("Layer C, code files with the largest effect on the structure score: " + "; ".join(files) + ".")
            lines.append(f"Touched files total {signed(graph['touched_files_total'])}, untouched files total "
                         f"{signed(graph['untouched_files_total'])}. GNN's own risk score {fmt(graph['gnn_probability'])}.")
    return Card(id=f"pr:{sample_id}", kind="pr", title=f"PR {sample_id}", text="\n".join(lines),
                meta={"sample_id": sample_id, "pr_number": _pr_order(sample_id)[1], "split": row["split"],
                      "label": row["label"], "probability": probability, "predicted_risky": predicted,
                      "explained": report is not None})


def predictions_card(inputs: dict[str, Any], split: str) -> Card:
    threshold = inputs["threshold"]
    lines = [f"Fusion predictions for every {split} PR (threshold {fmt(threshold)}). "
             "Format: PR, true label, fusion risk score, decision."]
    counts = Counter()
    for sample_id, row in inputs["rows"].items():
        if row["split"] != split:
            continue
        probability = float(inputs["predictions"][sample_id]["p_fusion"])
        predicted = int(probability >= threshold)
        outcome = {(1, 1): "true positive", (0, 1): "false positive", (0, 0): "true negative",
                   (1, 0): "false negative"}[(row["label"], predicted)]
        counts[outcome] += 1
        lines.append(f"{sample_id}: label {row['label']}, risk {fmt(probability)}, "
                     f"{'risky' if predicted else 'not risky'} ({outcome})")
    lines.append("Totals: " + ", ".join(f"{name} {counts[name]}" for name in
                                         ("true positive", "false positive", "true negative", "false negative")) + ".")
    return Card(id=f"predictions:{split}", kind="predictions", title=f"Fusion predictions, {split} split",
                text="\n".join(lines), meta={"split": split})


def model_card(inputs: dict[str, Any]) -> Card:
    metrics = inputs["metrics"]
    names = {"always_risky": "Always risky (baseline)", "gnn_only": "GNN only",
             "codereviewer_only": "CodeReviewer only", "fusion": "Fusion"}
    lines = ["Model results on the TEST split (threshold picked on validation). Ranges are bootstrap 95% ranges."]
    for key, label in names.items():
        result = metrics["results"].get(key)
        if not result:
            continue
        test, ranges = result["test"], result.get("test_bootstrap", {})
        f1_range = ranges.get("f1_95_range")
        ap_range = ranges.get("pr_auc_95_range")
        lines.append(f"{label}: F1 {fmt(test['f1'])}{_range(f1_range)}, precision {fmt(test['precision'])}, "
                     f"recall {fmt(test['recall'])}, PR-AUC {fmt(test['pr_auc_average_precision'])}{_range(ap_range)}, "
                     f"true positives {test['true_positive']}, false positives {test['false_positive']}, "
                     f"true negatives {test['true_negative']}, false negatives {test['false_negative']}.")
    validation = metrics["results"]["fusion"]["validation"]
    lines.append(f"Fusion on VALIDATION: F1 {fmt(validation['f1'])}, PR-AUC "
                 f"{fmt(validation['pr_auc_average_precision'])} ({validation['count']} PRs, "
                 f"{validation['count'] - validation['positives']} safe).")
    reported = metrics.get("gnn_reported_by_training", {}).get("test")
    if reported:
        lines.append(f"The GNN's own reported test result (from its training run): F1 {fmt(reported['f1'])}, "
                     f"precision {fmt(reported['precision'])}, recall {fmt(reported['recall'])}, "
                     f"PR-AUC {fmt(reported['pr_auc_average_precision'])}.")
    settings = metrics.get("settings", {})
    lines.append(f"Fusion settings: {settings.get('model')} classifier, {settings.get('pca_dims')} PCA numbers per "
                 f"input, threshold {fmt(inputs['threshold'])} ({settings.get('threshold_rule')}).")
    for warning in metrics.get("warnings", []):
        lines.append(f"Warning: {warning}")
    return Card(id="model:fusion", kind="model", title="Model results (fusion and baselines)",
                text="\n".join(lines), meta={"version": metrics.get("version")})


def dataset_card(inputs: dict[str, Any]) -> Card:
    rows = list(inputs["rows"].values())
    repos = sorted({row["sample_id"].split("#")[0] for row in rows})
    lines = [f"Dataset: {len(rows)} PRs from {', '.join(repos)}."]
    for split in SPLITS:
        members = [row for row in rows if row["split"] == split]
        positives = sum(row["label"] for row in members)
        lines.append(f"{split}: {len(members)} PRs, {positives} risky (label 1), {len(members) - positives} safe (label 0).")
    total_positive = sum(row["label"] for row in rows)
    lines.append(f"Overall: {total_positive} risky and {len(rows) - total_positive} safe.")
    if inputs["purged"]:
        lines.append(f"Purged (removed because their six-month window crosses a split cutoff): "
                     f"{len(inputs['purged'])} PRs: {', '.join(inputs['purged'])}.")
    cutoffs = (inputs.get("gnn_metrics") or {}).get("cutoffs")
    if cutoffs:
        lines.append(f"Split cutoffs: train outcomes known by {cutoffs.get('train', '')[:10]}, "
                     f"validation by {cutoffs.get('validation', '')[:10]}; test PRs merged after the second cutoff.")
    return Card(id="dataset", kind="dataset", title="Dataset and splits", text="\n".join(lines),
                meta={"count": len(rows)})


def doc_cards(docs_dir: Path) -> list[Card]:
    cards = []
    for path in sorted(docs_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        heading, body = None, []
        for line in path.read_text(encoding="utf-8").splitlines() + ["## "]:
            if line.startswith("## "):
                if heading and any(text.strip() for text in body):
                    text = " ".join(" ".join(body).split())
                    cards.append(Card(id=f"doc:{path.stem}#{_slug(heading)}", kind="doc", title=heading, text=text,
                                      meta={"file": path.name}))
                heading, body = line[3:].strip(), []
            elif heading is not None and not line.startswith("# "):
                body.append(line)
    return cards


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _range(values: list[float] | None) -> str:
    return f" (range {fmt(values[0], 2)}-{fmt(values[1], 2)})" if values else ""


# --- saving ----------------------------------------------------------------------------------

def save_cards(output_dir: Path, cards: list[Card], sources: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / "cards.jsonl.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(json.dumps(card.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(output_dir / "cards.jsonl")
    info = output_dir / "kb.json.tmp"
    info.write_text(json.dumps({"schema_version": 1, "cards": len(cards),
                                "kinds": dict(Counter(card.kind for card in cards)), "sources": sources},
                               indent=2, sort_keys=True) + "\n", encoding="utf-8")
    info.replace(output_dir / "kb.json")


def load_cards(path: Path) -> list[Card]:
    with Path(path).open(encoding="utf-8") as handle:
        return [Card(**json.loads(line)) for line in handle if line.strip()]
