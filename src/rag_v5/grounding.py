"""Check generated claims against the supplied attribution and retrieved cards."""
from __future__ import annotations

import json
import re
from typing import Any

# Allow normal sentence punctuation after a number (for example ``0.409.``),
# while still avoiding pieces of identifiers and multi-dot version strings.
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w|\.\d)")


def _matches_source_number(claim: str, source_numbers: set[float]) -> bool:
    """Accept exact values or ordinary decimal rounding of an input value."""
    value = float(claim)
    decimals = len(claim.partition(".")[2]) if "." in claim else 0
    # A value printed to d decimal places represents a rounding interval with
    # half a unit in its final place. Keep a tiny epsilon for binary floats.
    tolerance = 0.5 * (10 ** -decimals) + 1e-12
    return any(abs(value - source) <= tolerance for source in source_numbers)


def edge_label(edge: dict[str, Any]) -> str:
    return f"{edge['source']} -> {edge['relation']} -> {edge['target']}"


def violations(answer: dict[str, Any], attribution: dict[str, Any], cards: list[dict[str, Any]]) -> list[str]:
    """Return every unsupported edge, principle or numeric claim found in output."""
    issues = []
    allowed_edges = {edge_label(e) for e in attribution.get("top_edges", [])}
    allowed_nodes = {n.get("id") for n in attribution.get("top_nodes", [])}
    allowed_principles = {c["id"] for c in cards}
    evidence = answer.get("evidence", [])
    if not isinstance(evidence, list):
        issues.append("Evidence must be a list")
        evidence = []
    principles = answer.get("principles", [])
    if not isinstance(principles, list):
        issues.append("Principles must be a list")
        principles = []
    for item in evidence:
        if not isinstance(item, dict) or item.get("edge") not in allowed_edges | allowed_nodes:
            issues.append(f"Unsupported evidence: {item!r}")
    for principle in principles:
        if principle not in allowed_principles:
            issues.append(f"Unretrieved principle: {principle}")

    source_numbers = {float(match.group()) for match in NUMBER.finditer(json.dumps(attribution, ensure_ascii=False))}
    prose = " ".join(str(answer.get(k, "")) for k in ("explanation", "confidence_note"))
    prose += " " + " ".join(str(item.get("why", "")) for item in evidence if isinstance(item, dict))
    suggestion = answer.get("suggestion") or {}
    if not isinstance(suggestion, dict):
        issues.append("Suggestion must be an object")
        suggestion = {}
    steps = [re.sub(r"^\s*\d+[.)]\s*", "", str(value))
             for value in suggestion.get("steps", [])]
    prose += " " + " ".join(steps)
    for match in NUMBER.finditer(prose):
        if not _matches_source_number(match.group(), source_numbers):
            issues.append(f"Unsupported number: {match.group()}")
    return issues
