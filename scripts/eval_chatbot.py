"""Evaluate the chatbot on a fixed question set and write a report table.

    python scripts/eval_chatbot.py --manifest artifacts/gnn_embeddings_v3.json --retrieval-only   # free, instant
    python scripts/eval_chatbot.py --manifest artifacts/gnn_embeddings_v3.json                    # real Groq answers

The full run asks every question (waiting --pause seconds between them to stay inside the
Groq free-tier limits) and saves each answer as soon as it arrives in
data/eval/<version>/answers.jsonl, so an interrupted run continues where it stopped
(use --fresh to start over). Results: data/eval/<version>/results.json and results.md.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fusion.data import manifest_version  # noqa: E402
from src.rag.answer import Answer  # noqa: E402
from src.rag.api import Chatbot, load_config  # noqa: E402
from src.rag.evaluate import load_questions, markdown_table, retrieval_only, score, summarize  # noqa: E402
from src.rag.knowledge import load_cards  # noqa: E402
from src.rag.llm import ChatModel, LLMError  # noqa: E402
from src.rag.retrieval import Retriever  # noqa: E402


def main(argv: list[str] | None = None, llm_factory: Callable[[dict[str, Any]], ChatModel] | None = None,
         root: Path = ROOT, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description="Score the chatbot on a fixed question set.")
    parser.add_argument("--manifest", type=Path, required=True, help="e.g. artifacts/gnn_embeddings_v3.json")
    parser.add_argument("--questions", type=Path, help="Default: docs/eval/chatbot_questions_<version>.json")
    parser.add_argument("--retrieval-only", action="store_true", help="Only check retrieval (no Groq calls)")
    parser.add_argument("--pause", type=float, default=25.0, help="Seconds between Groq calls (default 25)")
    parser.add_argument("--fresh", action="store_true", help="Ignore saved answers and ask everything again")
    parser.add_argument("--redo", nargs="+", default=[], metavar="ID",
                        help="Ask these question ids again (e.g. --redo q01); the rest are re-scored from saved answers")
    parser.add_argument("--output-dir", type=Path, help="Default: data/eval/<version>")
    args = parser.parse_args(argv)
    version = manifest_version(args.manifest)
    if version is None:
        parser.error("cannot tell the data version from the manifest name (expected ..._v<number>.json)")
    questions_path = args.questions or root / "docs/eval" / f"chatbot_questions_{version}.json"
    output_dir = args.output_dir or root / "data/eval" / version
    kb_path = root / "data/kb" / version / "cards.jsonl"
    for name, path, hint in (("question set", questions_path, ""),
                             ("knowledge base", kb_path, " Run scripts/build_kb.py first.")):
        if not path.is_file():
            print(f"Missing {name}: {path}.{hint}")
            return 2
    questions = load_questions(questions_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.retrieval_only:
        top_k = int(load_config(root / "config/chatbot.json")["top_k"])
        rows = retrieval_only(questions, Retriever(load_cards(kb_path)), top_k)
        for row in rows:
            print(f"{row['id']} {'ok  ' if row['retrieval'] else 'MISS'} "
                  f"{'' if row['retrieval'] else 'missing ' + ', '.join(row['missing_cards'])}")
        summary = summarize(rows)
        _write_json(output_dir / "retrieval.json", {"summary": summary, "rows": rows})
        print(f"Retrieval hit rate: {summary['retrieval_hit_rate']:.0%} ({len(rows)} questions)")
        return 0

    try:
        bot = Chatbot.from_version(version, llm_factory=llm_factory, root=root)
    except (FileNotFoundError, LLMError, ValueError) as exc:
        print(exc)
        return 2
    answers_path = output_dir / "answers.jsonl"
    saved = {} if args.fresh else _load_answers(answers_path)
    if args.fresh and answers_path.exists():
        answers_path.unlink()
    unknown = [qid for qid in args.redo if qid not in {item["id"] for item in questions}]
    if unknown:
        print(f"Unknown question id(s): {', '.join(unknown)}")
        return 2
    for item in questions:
        if item["id"] in args.redo:
            saved.pop(_key(item), None)
    print(f"Evaluating {len(questions)} questions with {bot.llm.name} | saved answers reused: "
          f"{sum(1 for item in questions if _key(item) in saved)}")
    asked = 0
    for number, item in enumerate(questions, 1):
        if _key(item) in saved:
            continue
        bot.reset()
        parent = item.get("follow_up_of")
        if parent:
            parent_item = next(question for question in questions if question["id"] == parent)
            bot.remember(_to_answer(saved[_key(parent_item)]))
        if asked:
            sleep(args.pause)
        try:
            answer = bot.ask(item["question"])
        except LLMError as exc:
            print(f"[{number}/{len(questions)}] {item['id']} stopped: {exc}\nSaved answers are kept; run again to continue.")
            return 1
        asked += 1
        record = {"key": _key(item), **answer.to_dict()}
        saved[_key(item)] = record
        _save_answers(answers_path, saved)
        print(f"[{number}/{len(questions)}] {item['id']} answered by {answer.model}")

    rows = [score(item, saved[_key(item)]) for item in questions]
    summary = summarize(rows)
    _write_json(output_dir / "results.json", {"summary": summary, "rows": rows})
    table = markdown_table(rows, questions)
    (output_dir / "results.md").write_text(_report(summary, table), encoding="utf-8")
    print("\n" + table)
    print(f"\nPassed {summary['passed']} | retrieval {summary['retrieval_hit_rate']:.0%} | facts "
          f"{summary['fact_accuracy']:.0%} | grounded {summary['grounded_rate']:.0%} | refusals "
          f"{summary['correct_refusals']}")
    for row in rows:
        if not row["passed"]:
            reasons = []
            if row["missing_cards"]:
                reasons.append(f"missing cards {row['missing_cards']}")
            if row["missing_facts"]:
                reasons.append(f"missing facts {row['missing_facts']}")
            if not row["grounded"]:
                reasons.append(f"unsupported numbers {row['unsupported_numbers']}")
            if not row["refusal_ok"]:
                reasons.append("did not refuse")
            print(f"  {row['id']}: " + "; ".join(reasons))
    print(f"Saved: {output_dir / 'results.md'}")
    return 0


def _key(item: dict[str, Any]) -> str:
    return f"{item['id']}::{item['question']}"


def _load_answers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {record["key"]: record for record in records}


def _save_answers(path: Path, saved: dict[str, dict[str, Any]]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in saved.values()),
                         encoding="utf-8")
    temporary.replace(path)


def _to_answer(record: dict[str, Any]) -> Answer:
    fields = {name: record[name] for name in ("question", "text", "cards", "citations", "unknown_citations",
                                              "unsupported_numbers", "model", "note") if name in record}
    return Answer(**fields)


def _report(summary: dict[str, Any], table: str) -> str:
    return (f"# Chatbot evaluation\n\nModel(s): {', '.join(summary.get('models', []))}\n\n"
            f"- Questions passed: {summary['passed']}\n"
            f"- Retrieval hit rate: {summary['retrieval_hit_rate']:.0%}\n"
            f"- Fact accuracy: {summary['fact_accuracy']:.0%}\n"
            f"- Grounded answers (no unsupported numbers or citations): {summary['grounded_rate']:.0%}\n"
            f"- Correct refusals of off-topic questions: {summary['correct_refusals']}\n\n{table}\n")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
