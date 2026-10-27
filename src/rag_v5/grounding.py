"""Check generated claims against the supplied attribution and retrieved cards."""
from __future__ import annotations

import json
import re
from typing import Any

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")


def edge_label(edge: dict[str, Any]) -> str:
    return f"{edge['source']} -> {edge['relation']} -> {edge['target']}"


def violations(answer: dict[str, Any], attribution: dict[str, Any], cards: list[dict[str, Any]]) -> list[str]:
    """Return every unsupported edge, principle or numeric claim found in output."""
    issues = []
    allowed_edges = {edge_label(e) for e in attribution.get("top_edges", [])}
    allowed_nodes = {n.get("id") for n in attribution.get("top_nodes", [])}
    allowed_principles = {c["id"] for c in cards}
    for item in answer.get("evidence", []):
        if not isinstance(item, dict) or item.get("edge") not in allowed_edges | allowed_nodes:
            issues.append(f"Unsupported evidence: {item!r}")
    for principle in answer.get("principles", []):
        if principle not in allowed_principles:
            issues.append(f"Unretrieved principle: {principle}")

    source_numbers = {float(match.group()) for match in NUMBER.finditer(json.dumps(attribution, ensure_ascii=False))}
    prose = " ".join(str(answer.get(k, "")) for k in ("explanation", "confidence_note"))
    prose += " " + " ".join(str(item.get("why", "")) for item in answer.get("evidence", []) if isinstance(item, dict))
    suggestion = answer.get("suggestion") or {}
    prose += " " + " ".join(str(value) for value in suggestion.get("steps", []))
    for match in NUMBER.finditer(prose):
        if float(match.group()) not in source_numbers:
            issues.append(f"Unsupported number: {match.group()}")
    return issues
