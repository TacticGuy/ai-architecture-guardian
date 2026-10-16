"""The chatbot's public API. The web API (and anything else) should use only this module.

    bot = Chatbot.from_version("v3")            # reads data/kb/v3/cards.jsonl and config/chatbot.json
    answer = bot.ask("Why was PR #5648 flagged as risky?")
    answer.text, answer.citations, answer.grounded

Functions here never change retrieval or prompts; they only call into them, so the UI can be
redesigned freely without affecting how answers are produced.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from src.rag.answer import SYSTEM_PROMPT, Answer, build_user_message, check_answer
from src.rag.knowledge import Card, load_cards
from src.rag.llm import ChatModel, FallbackChat, GroqChat
from src.rag.retrieval import Retriever, mentioned_pr_numbers

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = {"provider": "groq",
                  "model": "openai/gpt-oss-120b", "model_options": {"reasoning_effort": "low", "include_reasoning": False},
                  "fallback_model": "qwen/qwen3.8-27b", "fallback_options": {"reasoning_effort": "none"},
                  "top_k": 6, "temperature": 0.0, "max_tokens": 1200}


def load_config(path: Path = ROOT / "config/chatbot.json") -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path.is_file():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


class Chatbot:
    def __init__(self, cards: list[Card], llm: ChatModel, top_k: int = 6, version: str | None = None,
                 root: Path = ROOT) -> None:
        if not cards:
            raise ValueError("the knowledge base is empty; run scripts/build_kb.py first")
        self.cards, self.llm, self.top_k, self.version, self.root = cards, llm, top_k, version, root
        self.retriever = Retriever(cards)
        self.history: list[tuple[str, str]] = []
        self._context_prs: list[int] = []

    @classmethod
    def from_version(cls, version: str, llm: ChatModel | None = None, root: Path = ROOT,
                     llm_factory: Callable[[dict[str, Any]], ChatModel] | None = None) -> "Chatbot":
        kb_path = root / "data/kb" / version / "cards.jsonl"
        if not kb_path.is_file():
            raise FileNotFoundError(f"{kb_path} not found. Run: python scripts/build_kb.py "
                                    f"--manifest artifacts/gnn_embeddings_{version}.json")
        config = load_config(root / "config/chatbot.json")
        if llm is None:
            _load_env(root / ".env")
            llm = (llm_factory or _groq)(config)
        return cls(load_cards(kb_path), llm, int(config["top_k"]), version, root)

    # --- questions ---------------------------------------------------------------------------

    def ask(self, question: str, remember: bool = True) -> Answer:
        question = question.strip()
        if not question:
            raise ValueError("empty question")
        numbers = mentioned_pr_numbers(question)
        hits = self.retriever.retrieve(question, self.top_k, context_prs=None if numbers else self._context_prs)
        text = self.llm.complete(SYSTEM_PROMPT, build_user_message(question, hits, self.history if remember else None))
        answer = check_answer(question, text, hits, getattr(self.llm, "last_used", getattr(self.llm, "name", "")),
                              getattr(self.llm, "note", ""))
        if remember:
            self.remember(answer)
        return answer

    def remember(self, answer: Answer) -> None:
        """Add an answer to the conversation, so a follow-up question can refer back to it."""
        self.history.append((answer.question, answer.text))
        self.history = self.history[-4:]
        pinned = [card["id"] for card in answer.cards if card.get("reason") == "pr-number"]
        numbers = [self.card(card_id).meta.get("pr_number") for card_id in pinned if self.card(card_id)]
        self._context_prs = [number for number in numbers if isinstance(number, int)] or self._context_prs

    def reset(self) -> None:
        self.history, self._context_prs = [], []

    # --- data for a UI (no language model involved) ----------------------------------------------

    def list_prs(self) -> list[dict[str, Any]]:
        return [dict(card.meta) for card in self.cards if card.kind == "pr"]

    def card(self, card_id: str) -> Card | None:
        return next((card for card in self.cards if card.id == card_id), None)

    def pr_details(self, sample_id: str) -> dict[str, Any]:
        """Everything known about one PR: its card, and its full XAI explanation if it exists."""
        card = self.card(f"pr:{sample_id}")
        if card is None:
            raise KeyError(f"unknown PR {sample_id}")
        details: dict[str, Any] = {"card": card.text, **card.meta, "explanation": None}
        if self.version:
            path = self.root / "data/xai" / self.version / f"{sample_id.replace('/', '__').replace('#', '__')}.json"
            if path.is_file():
                details["explanation"] = json.loads(path.read_text(encoding="utf-8"))
        return details

    def model_summary(self) -> str:
        card = self.card("model:fusion")
        return card.text if card else ""

    def model_metrics(self) -> dict[str, Any]:
        """The fusion run's metrics.json (all four models, ranges, warnings), or {} if missing."""
        path = self.root / "data/fusion" / str(self.version) / "metrics.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def dataset_summary(self) -> dict[str, Any]:
        """Split sizes, risky counts, purged PRs and cutoffs (from the dataset card)."""
        card = self.card("dataset")
        return dict(card.meta) if card else {}

    def predictions(self) -> list[dict[str, str]]:
        path = self.root / "data/fusion" / str(self.version) / "predictions.csv"
        if not path.is_file():
            return []
        with path.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))


def _groq(config: dict[str, Any]) -> ChatModel:
    common = {"temperature": float(config["temperature"]), "max_tokens": int(config["max_tokens"])}
    primary = GroqChat(config["model"], options=config.get("model_options"), **common)
    fallback = (GroqChat(config["fallback_model"], options=config.get("fallback_options"), **common)
                if config.get("fallback_model") else None)
    return FallbackChat(primary, fallback)


def _load_env(path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is in requirements.txt
        return
    load_dotenv(path)
