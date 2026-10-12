"""Chat with the project's knowledge base in the terminal (answers come from Groq).

    python scripts/chat.py --manifest artifacts/gnn_embeddings_v3.json
    python scripts/chat.py --manifest artifacts/gnn_embeddings_v3.json -q "Why is PR #5648 risky?"
    python scripts/chat.py --list-models        # which Groq models your key can use

Needs: data/kb/<version>/cards.jsonl (scripts/build_kb.py) and GROQ_API_KEY in .env.
Every answer lists the cards it used, and warns if it cites an unknown card or quotes a
number that is not in those cards. Type 'reset' to forget the conversation, 'exit' to quit.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fusion.data import manifest_version  # noqa: E402
from src.rag.answer import Answer  # noqa: E402
from src.rag.api import Chatbot, _load_env, load_config  # noqa: E402
from src.rag.llm import ChatModel, LLMError, list_models  # noqa: E402


def main(argv: list[str] | None = None, llm_factory: Callable[[dict[str, Any]], ChatModel] | None = None,
         read: Callable[[str], str] = input, root: Path = ROOT,
         models_lister: Callable[[], list[str]] = list_models) -> int:
    parser = argparse.ArgumentParser(description="Ask questions about the project's predictions and explanations.")
    parser.add_argument("--manifest", type=Path, help="e.g. artifacts/gnn_embeddings_v3.json")
    parser.add_argument("--list-models", action="store_true", help="List the Groq models your key can use, then exit")
    parser.add_argument("-q", "--question", help="Ask one question and exit")
    parser.add_argument("--show-context", action="store_true", help="Also print the cards sent to the model")
    args = parser.parse_args(argv)
    if args.list_models:
        return _list_models(root, models_lister)
    if args.manifest is None:
        parser.error("--manifest is required")
    version = manifest_version(args.manifest)
    if version is None:
        parser.error("cannot tell the data version from the manifest name (expected ..._v<number>.json)")

    try:
        bot = Chatbot.from_version(version, llm_factory=llm_factory, root=root)
    except (FileNotFoundError, LLMError, ValueError) as exc:
        print(exc)
        return 2
    print(f"AI Architecture Guardian chatbot | data {version} | {len(bot.cards)} cards | model {bot.llm.name}")

    if args.question:
        return _ask(bot, args.question, args.show_context)
    print("Ask about any PR (e.g. 'Why is PR #5648 flagged?'), the model, the data or the method. "
          "Type 'reset' or 'exit'.")
    while True:
        try:
            question = read("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.lower() in ("exit", "quit"):
            return 0
        if question.lower() == "reset":
            bot.reset()
            print("Conversation cleared.")
            continue
        if question:
            _ask(bot, question, args.show_context)


def _list_models(root: Path, lister: Callable[[], list[str]]) -> int:
    _load_env(root / ".env")
    config = load_config(root / "config/chatbot.json")
    try:
        models = lister()
    except LLMError as exc:
        print(exc)
        return 2
    print("Models your Groq key can use (* = set in config/chatbot.json):")
    for model in models:
        mark = "*" if model in (config.get("model"), config.get("fallback_model")) else " "
        print(f" {mark} {model}")
    missing = [name for name in (config.get("model"), config.get("fallback_model")) if name and name not in models]
    if missing:
        print(f"Not available to this key: {', '.join(missing)}. Change config/chatbot.json.")
    return 0


def _ask(bot: Chatbot, question: str, show_context: bool) -> int:
    try:
        answer = bot.ask(question)
    except LLMError as exc:
        print(f"Bot: (no answer) {exc}")
        return 1
    _print(answer, show_context, bot)
    return 0


def _print(answer: Answer, show_context: bool, bot: Chatbot) -> None:
    print(f"\nBot: {answer.text}")
    if answer.note:
        print(f"Note: {answer.note}")
    print("Sources: " + ", ".join(f"{card['id']} ({card['reason']})" for card in answer.cards))
    if answer.unknown_citations:
        print(f"WARNING: cites cards it was not given: {', '.join(answer.unknown_citations)}")
    if answer.unsupported_numbers:
        print(f"WARNING: these numbers are not in the source cards, double-check them: "
              f"{', '.join(answer.unsupported_numbers)}")
    if show_context:
        for card in answer.cards:
            found = bot.card(card["id"])
            print(f"\n--- [{card['id']}]\n{found.text if found else ''}")


if __name__ == "__main__":
    raise SystemExit(main())
