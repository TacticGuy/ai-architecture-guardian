"""Card loading and two deterministic retrieval modes."""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .signature import TAGS

TOKEN = re.compile(r"[a-z][a-z0-9_]+", re.I)


def load_cards(root: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2] / "docs" / "principles"
    cards = []
    for path in sorted(root.glob("*.md")):
        for section in re.split(r"(?=^## )", path.read_text(encoding="utf-8"), flags=re.M):
            if not section.startswith("## "):
                continue
            lines = section.strip().splitlines()
            metadata: dict[str, Any] = {}
            body_start = 1
            for index, line in enumerate(lines[1:], 1):
                if ":" not in line or line.startswith("**"):
                    body_start = index
                    break
                key, value = line.split(":", 1)
                if key not in {"id", "kind", "graph_signals", "relations", "sources"}:
                    body_start = index
                    break
                metadata[key] = value.strip()
                body_start = index + 1
            for key in ("graph_signals", "relations"):
                metadata[key] = [s.strip() for s in metadata.get(key, "").strip("[]").split(",") if s.strip()]
            if not metadata.get("id") or not set(metadata["graph_signals"]) <= TAGS:
                raise ValueError(f"Invalid card in {path}: {lines[0]}")
            cards.append({"title": lines[0][3:], "text": "\n".join(lines[body_start:]), "file": str(path), **metadata})
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate design-principle card ids")
    return cards


def _bm25(query: str, cards: list[dict[str, Any]]) -> list[float]:
    docs = [Counter(TOKEN.findall((c["title"] + " " + c["text"]).lower())) for c in cards]
    q = set(TOKEN.findall(query.lower()))
    lengths = [sum(d.values()) for d in docs]
    avg = sum(lengths) / len(lengths) if lengths else 1
    scores = []
    for doc, length in zip(docs, lengths):
        score = 0.0
        for word in q:
            freq = doc[word]
            if not freq:
                continue
            df = sum(word in d for d in docs)
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            score += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * length / avg))
        scores.append(score)
    return scores


def retrieve_by_signature(sig: dict[str, Any], cards: list[dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    text_scores = _bm25(sig.get("evidence_text", ""), cards)
    ranked = []
    for card, text_score in zip(cards, text_scores):
        matched = sorted(set(card["graph_signals"]) & sig["tags"].keys())
        score = sum(sig["tags"][tag] for tag in matched)
        relations = sorted(set(card["relations"]) & set(sig.get("relations", [])))
        score += 0.03 * len(relations)
        ranked.append({**card, "score": score, "matched_tags": matched, "matched_relations": relations,
                       "reason": f"Matched evidence: {', '.join(matched or relations) or 'BM25 tie-break'}",
                       "_tie": text_score})
    ranked.sort(key=lambda c: (-c["score"], -c["_tie"], c["id"]))
    return [{key: value for key, value in c.items() if key != "_tie"} for c in ranked[:k]]


def retrieve_by_text(text: str, cards: list[dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    ranked = [{**c, "score": score, "matched_tags": [], "matched_relations": [],
               "reason": "BM25 title and diff match"} for c, score in zip(cards, _bm25(text, cards))]
    return sorted(ranked, key=lambda c: (-c["score"], c["id"]))[:k]
