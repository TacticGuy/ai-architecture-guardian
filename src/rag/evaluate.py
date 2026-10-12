"""Score the chatbot on a fixed question set (docs/eval/chatbot_questions_<version>.json).

Per question:
  retrieval  every expected card was among the cards sent to the model
  facts      share of required fact groups found in the answer (a group passes when any of
             its phrases appears, ignoring case)
  grounded   the fact check found no unsupported numbers and no unknown citations
  refusal    for off-topic questions: the answer says it does not have the information
A question passes when retrieval is right, all facts are present, it is grounded and,
for off-topic questions, it refuses.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from src.rag.retrieval import Retriever

_SPACES = re.compile(r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})


def normalize(text: str) -> str:
    """Lower case, every kind of space as one plain space, every kind of dash as '-'."""
    return _SPACES.sub(" ", text.translate(_DASHES)).lower().strip()


REFUSAL_PHRASES = ("don't have", "do not have", "not in the project outputs", "no information", "cannot answer",
                   "can't answer", "not available in")


def load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = data["questions"]
    ids = [item["id"] for item in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ids")
    for position, item in enumerate(questions):
        parent = item.get("follow_up_of")
        if parent and parent not in ids[:position]:
            raise ValueError(f"{item['id']}: follow_up_of must name an earlier question")
    return questions


def score(item: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    text = normalize(answer["text"])
    sent = {card["id"] for card in answer["cards"]}
    missing_cards = [card for card in item.get("expect_cards", []) if card not in sent]
    groups = item.get("must_include", [])
    missing_facts = [group for group in groups if not any(normalize(phrase) in text for phrase in group)]
    facts = 1.0 if not groups else (len(groups) - len(missing_facts)) / len(groups)
    refused = any(phrase in text for phrase in REFUSAL_PHRASES)
    refusal_ok = refused if item.get("refuse") else True
    grounded = bool(answer.get("grounded", True))
    return {"id": item["id"], "topic": item.get("topic", ""), "retrieval": not missing_cards, "facts": facts,
            "grounded": grounded, "refusal_ok": refusal_ok,
            "passed": not missing_cards and not missing_facts and grounded and refusal_ok,
            "missing_cards": missing_cards, "missing_facts": missing_facts,
            "unsupported_numbers": answer.get("unsupported_numbers", []), "model": answer.get("model", "")}


def retrieval_only(questions: list[dict[str, Any]], retriever: Retriever, top_k: int) -> list[dict[str, Any]]:
    """Retrieval hit rate without any language model (free and instant)."""
    pinned: dict[str, list[int]] = {}
    rows = []
    for item in questions:
        context = pinned.get(item.get("follow_up_of", ""), [])
        hits = retriever.retrieve(item["question"], top_k, context_prs=context or None)
        pinned[item["id"]] = [hit.card.meta["pr_number"] for hit in hits
                              if hit.reason == "pr-number" and isinstance(hit.card.meta.get("pr_number"), int)]
        sent = {hit.card.id for hit in hits}
        missing = [card for card in item.get("expect_cards", []) if card not in sent]
        rows.append({"id": item["id"], "topic": item.get("topic", ""), "retrieval": not missing, "missing_cards": missing})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if not count:
        return {"questions": 0}
    summary: dict[str, Any] = {"questions": count, "retrieval_hit_rate": sum(row["retrieval"] for row in rows) / count}
    if rows and "facts" in rows[0]:
        refusals = [row for row in rows if row["topic"] == "off-topic"]
        summary.update({
            "fact_accuracy": sum(row["facts"] for row in rows) / count,
            "grounded_rate": sum(row["grounded"] for row in rows) / count,
            "correct_refusals": f"{sum(row['refusal_ok'] for row in refusals)}/{len(refusals)}",
            "passed": f"{sum(row['passed'] for row in rows)}/{count}",
            "models": sorted({row["model"] for row in rows if row.get("model")}),
        })
    return summary


def markdown_table(rows: list[dict[str, Any]], questions: list[dict[str, Any]]) -> str:
    text = {item["id"]: item["question"] for item in questions}
    lines = ["| # | Question | Retrieval | Facts | Grounded | Pass |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {text[row['id']]} | {'yes' if row['retrieval'] else 'NO'} | "
                     f"{row['facts']:.0%} | {'yes' if row['grounded'] else 'NO'} | {'yes' if row['passed'] else 'NO'} |")
    return "\n".join(lines)
