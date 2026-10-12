"""Explain one PR's fusion risk score.

Layer A - structure vs diff: how much of the score came from the GNN vector (code structure)
          and how much from the CodeReviewer vector (the diff). For logistic regression this
          split is exact: base + structure + diff = the model's logit.
Layer B - hunk occlusion: hide one changed block (hunk) of the diff at a time, re-encode the
          diff with CodeReviewer, re-score, and see how much the risk drops. A big drop means
          that hunk pushed the risk up.

What it explains is what the MODEL relies on, not ground truth; with weak models the
explanations are weak too.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any

import torch

from src.fusion.model import FusionModel, _mlp_logits
from src.semantic.diff_encoder import DiffEncoder, graph_includes_path

_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class ExplanationError(ValueError):
    """The inputs needed for a faithful explanation do not match; refuse rather than mislead."""


# --- layer A ---------------------------------------------------------------------------------

def branch_contributions(model: FusionModel, gnn: torch.Tensor, diff: torch.Tensor) -> dict[str, Any]:
    """Split one PR's score into a structure part and a diff part, in logit units.

    Each part = logit(full) - logit(that input replaced by the training average). Because PCA
    features are centred on the training rows, "training average" means its features are 0.
    For logistic regression the parts add up exactly: base + structure + diff = logit.
    """
    matrices = {"gnn": gnn.reshape(1, -1).double(), "diff": diff.reshape(1, -1).double()}
    features = model.features(matrices)
    full = _logit(model, features)
    widths = [int(model.projections[name].components.shape[1]) for name in model.inputs]
    parts, start = {}, 0
    for name, width in zip(model.inputs, widths):
        hidden = features.clone()
        hidden[:, start:start + width] = 0.0
        parts[name] = full - _logit(model, hidden)
        start += width
    base = _logit(model, torch.zeros_like(features))
    return {"logit": full, "probability": _sigmoid(full), "base_logit": base,
            "structure_gnn": parts.get("gnn", 0.0), "diff_codereviewer": parts.get("diff", 0.0),
            "exact": model.kind == "logreg"}


def _logit(model: FusionModel, features: torch.Tensor) -> float:
    if model.kind == "logreg":
        return float(features @ model.params["weight"] + model.params["bias"])
    return float(_mlp_logits(model.params, features))


def _sigmoid(value: float) -> float:
    """Risk probability from a logit; written so very large logits (either sign) cannot overflow."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    small = math.exp(value)
    return small / (1.0 + small)


# --- layer B ---------------------------------------------------------------------------------

@dataclass
class Hunk:
    file: str
    index: int                    # position in the whole diff, 0-based
    header: str
    new_start: int
    new_length: int
    lines: list[str] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(1 for line in self.lines if line.startswith("+"))

    @property
    def removed(self) -> int:
        return sum(1 for line in self.lines if line.startswith("-"))

    def snippet(self, max_lines: int = 6, width: int = 120) -> list[str]:
        changed = [line for line in self.lines if line.startswith(("+", "-"))]
        return [line[:width] for line in changed[:max_lines]]


@dataclass
class ParsedDiff:
    files: list[tuple[str, list[str], list[Hunk]]]    # (path, header lines, hunks)

    @property
    def hunks(self) -> list[Hunk]:
        return [hunk for _, _, hunks in self.files for hunk in hunks]

    def render(self, skip: int | None = None) -> str:
        """The diff text again, optionally without the hunk whose ``index`` is ``skip``."""
        out: list[str] = []
        for _, header, hunks in self.files:
            kept = [hunk for hunk in hunks if hunk.index != skip]
            if hunks and not kept:
                continue                               # file lost its only hunk(s): drop it entirely
            out.extend(header)
            for hunk in kept:
                out.append(hunk.header)
                out.extend(hunk.lines)
        return "\n".join(out) + ("\n" if out else "")


def parse_diff(diff_text: str) -> ParsedDiff:
    files: list[tuple[str, list[str], list[Hunk]]] = []
    current_hunk: Hunk | None = None
    counter = 0
    for line in diff_text.splitlines():
        header = _FILE_HEADER.match(line)
        if header:
            files.append((header.group(2), [line], []))
            current_hunk = None
            continue
        if not files:
            continue
        hunk_header = _HUNK_HEADER.match(line)
        if hunk_header:
            current_hunk = Hunk(files[-1][0], counter, line, int(hunk_header.group(3)),
                                int(hunk_header.group(4) if hunk_header.group(4) is not None else 1))
            files[-1][2].append(current_hunk)
            counter += 1
        elif current_hunk is not None:
            current_hunk.lines.append(line)
        else:
            files[-1][1].append(line)                  # index/---/+++ lines before the first hunk
    return ParsedDiff(files)


def explain_pr(*, model: FusionModel, encoder: DiffEncoder, analysis_settings: dict[str, Any],
               diff_text: str, gnn: torch.Tensor, stored_diff: torch.Tensor, max_hunks: int = 20,
               tolerance: float = 1e-4) -> dict[str, Any]:
    """Layers A and B for one PR. ``stored_diff`` is the saved CodeReviewer vector of this PR."""
    encoded = encoder.encode_diff(diff_text, analysis_settings, allow_fallback=False).vector.double()
    if not torch.allclose(encoded, stored_diff.double(), atol=tolerance, rtol=0):
        gap = float((encoded - stored_diff.double()).abs().max())
        raise ExplanationError(f"re-encoding the diff does not reproduce the saved vector (max difference "
                               f"{gap:.2e}); the model or settings differ from the ones used for training")
    contributions = branch_contributions(model, gnn, stored_diff)
    full_probability = contributions["probability"]

    parsed = parse_diff(diff_text)
    eligible = [hunk for hunk in parsed.hunks
                if not encoder.settings.graph_files_only or graph_includes_path(hunk.file, analysis_settings)]
    ranked = sorted(eligible, key=lambda hunk: (-(hunk.added + hunk.removed), hunk.index))
    chosen = sorted(ranked[:max_hunks], key=lambda hunk: hunk.index)

    no_diff_probability = _sigmoid(contributions["logit"] - contributions["diff_codereviewer"])
    effects = []
    for hunk in chosen:
        try:
            vector = encoder.encode_diff(parsed.render(skip=hunk.index), analysis_settings,
                                         allow_fallback=False).vector
            without = float(model.predict_proba({"gnn": gnn.reshape(1, -1), "diff": vector.reshape(1, -1)})[0])
            reference = "diff_without_this_hunk"
        except ValueError:                             # it was the only production change
            without, reference = no_diff_probability, "no_diff_information"
        last_line = hunk.new_start + max(hunk.new_length, 1) - 1
        effects.append({
            "file": hunk.file, "hunk_index": hunk.index, "new_lines": [hunk.new_start, last_line],
            "added": hunk.added, "removed": hunk.removed,
            "effect_on_risk": full_probability - without,   # > 0: this hunk pushed the risk up
            "reference": reference, "snippet": hunk.snippet()})
    effects.sort(key=lambda effect: (-effect["effect_on_risk"], effect["hunk_index"]))
    return {
        "probability": full_probability,
        "contributions": contributions,
        "hunks": effects,
        "hunk_counts": {"total": len(parsed.hunks), "in_analysed_files": len(eligible),
                        "explained": len(chosen), "skipped_by_cap": len(eligible) - len(chosen)},
    }
