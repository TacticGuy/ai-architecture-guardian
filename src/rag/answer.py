"""Turn retrieved cards into a grounded prompt, and check the model's answer against them.

Checks after every answer:
  * every [card-id] the answer cites must be one of the cards it was given;
  * every number in the answer must appear in those cards (a 0.598 may also appear as
    59.8%). Numbers that fail are reported, so a made-up number never goes unnoticed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from src.rag.knowledge import Card
from src.rag.retrieval import Hit

SYSTEM_PROMPT = """You are the assistant of AI Architecture Guardian, a student project that predicts whether \
a Python pull request (PR) touches code that will need an architectural refactor within six months.

Rules:
1. Answer ONLY from the cards given in the message. Do not use outside knowledge about the projects or PRs.
2. After each fact, cite the card it came from in square brackets, exactly as written, e.g. [pr:pallets/flask#5331] \
or [model:fusion].
3. Copy numbers exactly as they appear in the cards. Do not round, recompute or invent numbers.
4. If the cards do not contain the answer, say: "I don't have that in the project outputs." and suggest what to ask.
5. Risk scores are model outputs between 0 and 1, not calibrated probabilities. When you discuss how good the \
model is, mention the warnings in the model card (small data, wide ranges, comparison with the always-risky baseline).
6. Explanations (XAI) show what the model relies on, not proof of what causes risk. Do not guess at reasons \
that the cards do not state.
7. When you explain a single PR, always say its true label (risky or safe) and whether the prediction was correct \
or wrong, and, if the card has them, the touched-files and untouched-files totals from layer C.
8. Write in plain, simple English for an engineering student. Keep it short: a few sentences or bullet points."""

_CITATION = re.compile(r"\[([a-z]+:[^\]\s]+|dataset)\]")
_NUMBER = re.compile(r"(?<![\w.#/-])[-+]?\d+(?:\.\d+)?%?(?![\w/])")
_ANY_NUMBER = re.compile(r"\d+(?:\.\d+)?")                  # every number in a card, incl. both ends of 37-39
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})


@dataclass
class Answer:
    question: str
    text: str
    cards: list[dict[str, Any]]                       # id, title, reason for every card given to the model
    citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    model: str = ""
    note: str = ""                                     # e.g. "answered with the fallback model"

    @property
    def grounded(self) -> bool:
        return not self.unknown_citations and not self.unsupported_numbers

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "grounded": self.grounded}


def build_user_message(question: str, hits: list[Hit], history: list[tuple[str, str]] | None = None) -> str:
    parts = ["CARDS:"]
    for hit in hits:
        parts.append(f"[{hit.card.id}] {hit.card.title}\n{hit.card.text}")
    if history:
        parts.append("EARLIER IN THIS CHAT (for context only; facts must still come from the cards):")
        for previous_question, previous_answer in history[-2:]:
            parts.append(f"Q: {previous_question}\nA: {previous_answer}")
    parts.append(f"QUESTION: {question}")
    return "\n\n".join(parts)


def check_answer(question: str, text: str, hits: list[Hit], model: str = "", note: str = "") -> Answer:
    given = {hit.card.id for hit in hits}
    text = text.translate(_DASHES).replace("\u3010", "[").replace("\u3011", "]")   # 【card】 -> [card]
    cited = list(dict.fromkeys(_CITATION.findall(text)))
    allowed = _numbers_in(" ".join(hit.card.text + " " + hit.card.title + " " + hit.card.id for hit in hits))
    allowed |= _numbers_in(question)
    unsupported = []
    for raw in _NUMBER.findall(_CITATION.sub(" ", text)):
        if not _supported(raw, allowed):
            unsupported.append(raw)
    return Answer(question=question, text=text,
                  cards=[{"id": hit.card.id, "title": hit.card.title, "reason": hit.reason} for hit in hits],
                  citations=cited, unknown_citations=[card_id for card_id in cited if card_id not in given],
                  unsupported_numbers=list(dict.fromkeys(unsupported)), model=model, note=note)


def _numbers_in(text: str) -> set[float]:
    return {_value(raw) for raw in _ANY_NUMBER.findall(text.translate(_DASHES))}


def _value(raw: str) -> float:
    return round(float(raw.rstrip("%")), 6)


def _supported(raw: str, allowed: set[float]) -> bool:
    value = _value(raw)
    if abs(value) <= 10 and float(value).is_integer():
        return True                       # small counts like "2 files" or "3 layers" are not checked
    digits = len(raw.rstrip("%").split(".")[1]) if "." in raw else 0
    candidates = [(abs(value), digits)]
    if raw.endswith("%"):                         # 76.9% may stand for 0.769: two more decimal places
        candidates.append((abs(value) / 100, digits + 2))
    for candidate, places in candidates:
        for known in allowed:
            if abs(candidate - abs(known)) <= 1e-9:
                return True
            # the answer may shorten a card number: 0.769 -> 0.77, 2.6925 -> 2.69
            if candidate != 0 and places >= 1 and round(abs(known), places) == round(candidate, places):
                return True
    return False
