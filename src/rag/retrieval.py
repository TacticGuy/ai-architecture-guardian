"""Find the knowledge cards that can answer a question.

Two parts, both deterministic and model-free:
  * pinned cards: a PR number in the question ("#5331", "PR 5331", "pallets/flask#5331")
    always brings that PR's card; words like "accuracy" or "dataset" bring the model or
    dataset card;
  * BM25 keyword search (the classic search-engine ranking) over all cards for the rest.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

from src.rag.knowledge import Card

_TOKEN = re.compile(r"[a-z0-9_]+")
_PR_NUMBER = re.compile(r"(?:#|\bpr\s*#?\s*|\bpull request\s*#?\s*)(\d{1,6})\b", re.IGNORECASE)
_STOPWORDS = set("""a an the is are was were be been of to in on for and or with by at as it its this that
these those what which who whom why how does do did can could would should will i me my we our you your
about from into than then there their them they has have had not no yes so if but""".split())

# Topic words that must always bring a specific card, because BM25 alone can miss them.
_TOPICS = {
    "model:fusion": ("accuracy", "accurate", "f1", "precision", "recall", "pr-auc", "auc", "baseline",
                     "how good", "performance", "perform", "metric", "metrics", "results", "beat", "chance"),
    "dataset": ("dataset", "how many prs", "split", "splits", "purged", "purge", "cutoff", "train set",
                "training data", "data size"),
    "predictions:test": ("false positive", "false negative", "wrong", "mistake", "misclassified",
                         "which prs", "list of prs", "test prs", "correct"),
}


@dataclass
class Hit:
    card: Card
    score: float
    reason: str          # "pr-number", "topic" or "search"


_FOLLOW_UP = re.compile(r"\b(it|its|it's|this|that|these|those|they|them|their|same|above|previous|earlier|"
                        r"hunks?|files?|layers?|score|label|why|explain|more)\b", re.IGNORECASE)
_SPLIT_WORDS = {"predictions:train": ("train",), "predictions:validation": ("validation", "valid"),
                "predictions:test": ("test",)}


def is_follow_up(question: str) -> bool:
    """True for questions that refer back to an earlier PR ("and its top files?")."""
    return bool(_FOLLOW_UP.search(question))


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def mentioned_pr_numbers(text: str) -> list[int]:
    numbers = [int(value) for value in _PR_NUMBER.findall(text)]
    return list(dict.fromkeys(numbers))


class Retriever:
    def __init__(self, cards: list[Card], k1: float = 1.5, b: float = 0.75) -> None:
        self.cards = cards
        self.k1, self.b = k1, b
        self.documents = [tokenize(card.title + " " + card.text) for card in cards]
        self.lengths = [len(document) for document in self.documents]
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.frequencies = [Counter(document) for document in self.documents]
        document_frequency: Counter[str] = Counter()
        for document in self.documents:
            document_frequency.update(set(document))
        count = len(cards)
        self.idf = {term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
                    for term, frequency in document_frequency.items()}
        self.by_id = {card.id: card for card in cards}
        self.pr_cards: dict[int, list[Card]] = {}
        for card in cards:
            if card.kind == "pr" and isinstance(card.meta.get("pr_number"), int):
                self.pr_cards.setdefault(card.meta["pr_number"], []).append(card)

    def bm25(self, query: str) -> list[float]:
        terms = tokenize(query)
        scores = []
        for frequencies, length in zip(self.frequencies, self.lengths):
            score = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0)
                if frequency:
                    norm = frequency * (self.k1 + 1) / (
                        frequency + self.k1 * (1 - self.b + self.b * length / (self.average_length or 1)))
                    score += self.idf.get(term, 0.0) * norm
            scores.append(score)
        return scores

    def retrieve(self, question: str, k: int = 6, context_prs: list[int] | None = None) -> list[Hit]:
        """Return up to ``k`` cards: pinned ones first, then the best keyword matches."""
        hits: list[Hit] = []
        seen: set[str] = set()

        def add(card: Card, score: float, reason: str) -> None:
            if card.id not in seen:
                seen.add(card.id)
                hits.append(Hit(card, score, reason))

        numbers = mentioned_pr_numbers(question) or (list(context_prs or []) if is_follow_up(question) else [])
        for number in numbers:
            for card in self.pr_cards.get(number, []):
                add(card, float("inf"), "pr-number")
        lowered = question.lower()
        for card_id, words in _TOPICS.items():
            if not any(word in lowered for word in words):
                continue
            targets = [card_id]
            if card_id == "predictions:test":                # use the split the question names, test by default
                named = [table for table, split_words in _SPLIT_WORDS.items()
                         if any(re.search(rf"\b{word}", lowered) for word in split_words)]
                targets = named or [card_id]
            for target in targets:
                if target in self.by_id:
                    add(self.by_id[target], float("inf"), "topic")
        pinned_prs = sum(1 for hit in hits if hit.reason == "pr-number")
        # A question about named PRs gets only a couple of extra cards: sharper answers, fewer tokens.
        limit = min(max(k, len(hits)), len(hits) + 2) if pinned_prs else max(k, len(hits))
        ranked = sorted(zip(self.bm25(question), range(len(self.cards))), key=lambda pair: (-pair[0], pair[1]))
        for score, index in ranked:
            if len(hits) >= limit or score <= 0:
                break
            card = self.cards[index]
            if card.id in _SPLIT_WORDS and not any(word in lowered for word in _SPLIT_WORDS[card.id]):
                continue                                # big prediction tables only when their split is asked about
            add(card, score, "search")
        return hits
