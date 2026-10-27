"""Produce one auditable plain-English explanation from v5 graph attributions."""
from __future__ import annotations

import json
import os
from typing import Any

from .grounding import edge_label, violations
from .retrieval import load_cards, retrieve_by_signature, retrieve_by_text
from .signature import signature


def _default_llm() -> Any:
    from src.rag.llm import FallbackChat, GroqChat

    if not os.environ.get("GROQ_API_KEY"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    primary = GroqChat("openai/gpt-oss-120b", temperature=0)
    # Llama 3.3 70B was deprecated for free/developer plans in Aug 2026.
    fallback = GroqChat("openai/gpt-oss-20b", temperature=0)
    return FallbackChat(primary, fallback)


def _prompt(attribution: dict[str, Any], cards: list[dict[str, Any]]) -> tuple[str, str]:
    positive = sorted((e for e in attribution.get("top_edges", []) if e.get("attribution", 0) > 0),
                      key=lambda e: -e["attribution"])[:8]
    negative = sorted((e for e in attribution.get("top_edges", []) if e.get("attribution", 0) < 0),
                      key=lambda e: e["attribution"])[:3]
    evidence = {
        "title": attribution.get("title"), "risk_score": attribution.get("risk_score"),
        "threshold": attribution.get("threshold"), "layer_a": attribution.get("layer_a"),
        "edges": [{"edge": edge_label(e), "attribution": e["attribution"],
                   "added_in_pr": e.get("added_in_pr", False)} for e in positive + negative],
        "module_evidence": {name: attribution.get("module_evidence", {}).get(name)
                            for name in attribution.get("touched_modules", [])},
        "top_hunks": (attribution.get("top_hunks") or [])[:2],
        "cards": [{"id": c["id"], "title": c["title"], "text": c["text"]} for c in cards],
    }
    system = ("You explain a Python PR's architecture-risk model output. Use ONLY the supplied evidence. "
              "Never treat the score as a calibrated probability. Return strict JSON with keys verdict "
              "('degrading' or 'safe'), explanation (3-6 plain sentences), evidence (list of objects "
              "with edge and why), principles (retrieved card ids only), suggestion (refactoring, files, "
              "steps, optional code_sketch), and confidence_note. Cite edges exactly as provided. "
              "Never invent numbers, files, graph edges or principles. Suggest the smallest plausible fix; "
              "if evidence is weak, say so.")
    return system, json.dumps(evidence, ensure_ascii=False, sort_keys=True)


def explain_pr(attribution: dict[str, Any], mode: str = "signature", llm: Any = None) -> dict[str, Any]:
    """Explain one PR; retry grounding failure once and record all violations."""
    if mode not in {"signature", "text", "none"}:
        raise ValueError("mode must be signature, text or none")
    sig = signature(attribution)
    cards = load_cards()
    if mode == "signature":
        retrieved = retrieve_by_signature(sig, cards)
    elif mode == "text":
        diff_text = " ".join(" ".join(h.get("snippet", [])) for h in attribution.get("top_hunks", []))
        retrieved = retrieve_by_text(f"{attribution.get('title', '')} {diff_text}", cards)
    else:
        retrieved = []
    model = llm if llm is not None else _default_llm()
    system, user = _prompt(attribution, retrieved)
    attempts = []
    for _ in range(2):
        response = model.complete(system, user)
        try:
            answer = json.loads(response)
            if not isinstance(answer, dict):
                raise ValueError("JSON root is not an object")
            problems = violations(answer, attribution, retrieved)
            expected = "degrading" if attribution.get("risk_score", 0) >= attribution.get("threshold", 0) else "safe"
            if answer.get("verdict") != expected:
                problems.append(f"Verdict disagrees with model threshold: expected {expected}")
        except (ValueError, TypeError) as exc:
            answer, problems = {}, [f"Invalid JSON: {exc}"]
        attempts.append(problems)
        if not problems:
            return {**answer, "sample_id": attribution.get("sample_id"), "mode": mode,
                    "retrieved_cards": [{"id": c["id"], "reason": c["reason"]} for c in retrieved],
                    "grounding_violations": [], "attempt_violations": attempts}
        user += "\nYour previous response failed grounding: " + "; ".join(problems) + ". Repair it."
    return {"sample_id": attribution.get("sample_id"), "mode": mode, "status": "grounding_failed",
            "grounding_violations": attempts[-1], "attempt_violations": attempts,
            "retrieved_cards": [{"id": c["id"], "reason": c["reason"]} for c in retrieved]}
