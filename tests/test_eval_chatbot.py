"""Chatbot evaluation: question file checks, scoring, retrieval-only mode and the runner."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.rag.evaluate import load_questions, retrieval_only, score, summarize
from src.rag.knowledge import load_cards, save_cards
from src.rag.llm import LLMError
from src.rag.retrieval import Retriever
from tests.test_chatbot import ScriptedModel, project_cards

ROOT = Path(__file__).resolve().parents[1]

QUESTIONS = {"version": "v7", "questions": [
    {"id": "a", "topic": "single PR", "question": "Why is PR #30 risky?", "expect_cards": ["pr:o/r#30"],
     "must_include": [["0.765"], ["correct", "right"]]},
    {"id": "b", "topic": "follow-up", "question": "Which hunks mattered for it?", "follow_up_of": "a",
     "expect_cards": ["pr:o/r#30"], "must_include": [["207"]]},
    {"id": "c", "topic": "off-topic", "question": "What is the capital of France?", "refuse": True,
     "expect_cards": [], "must_include": []},
]}


def answer(text: str, cards=("pr:o/r#30",), grounded: bool = True) -> dict:
    return {"text": text, "cards": [{"id": card_id} for card_id in cards], "grounded": grounded,
            "unsupported_numbers": [] if grounded else ["9.99"], "model": "m"}


# --- question file and scoring ---------------------------------------------------------------

def test_question_file_must_have_unique_ids_and_earlier_parents(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    assert [item["id"] for item in load_questions(path)] == ["a", "b", "c"]
    bad = {"questions": [{"id": "x", "question": "?", "follow_up_of": "y"}, {"id": "y", "question": "?"}]}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="earlier question"):
        load_questions(path)
    path.write_text(json.dumps({"questions": [{"id": "x", "question": "1"}, {"id": "x", "question": "2"}]}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_questions(path)


def test_scoring_needs_cards_facts_grounding_and_refusals():
    item, refuse = QUESTIONS["questions"][0], QUESTIONS["questions"][2]
    assert score(item, answer("Scored 0.765, which is CORRECT."))["passed"]
    partial = score(item, answer("Scored 0.765."))
    assert partial["facts"] == 0.5 and not partial["passed"] and partial["missing_facts"] == [["correct", "right"]]
    assert not score(item, answer("Scored 0.765, correct.", cards=()))["retrieval"]
    assert not score(item, answer("Scored 0.765, correct.", grounded=False))["passed"]
    assert score(refuse, answer("I don't have that in the project outputs.", cards=()))["passed"]
    assert not score(refuse, answer("It is Paris.", cards=()))["refusal_ok"]


def test_unusual_spaces_and_dashes_do_not_hide_facts():
    item = {"id": "x", "question": "?", "expect_cards": [], "must_include": [["integrated gradients"], ["207-218"]]}
    result = score(item, answer("Layer C uses Integrated\u202fGradients on lines 207\u2011218."))
    assert result["facts"] == 1.0


def test_summary_counts():
    rows = [score(QUESTIONS["questions"][0], answer("0.765 correct")),
            score(QUESTIONS["questions"][2], answer("Paris", cards=()))]
    summary = summarize(rows)
    assert summary["passed"] == "1/2" and summary["correct_refusals"] == "0/1" and summary["retrieval_hit_rate"] == 1.0
    assert summary["fact_accuracy"] == 1.0


def test_retrieval_only_mode_carries_the_pr_into_follow_ups(tmp_path):
    cards, _ = project_cards(tmp_path)
    rows = retrieval_only(QUESTIONS["questions"], Retriever(cards), top_k=6)
    assert [row["retrieval"] for row in rows] == [True, True, True]


# --- the runner ----------------------------------------------------------------------------------

def setup_root(tmp_path: Path) -> Path:
    cards, _ = project_cards(tmp_path / "project")
    root = tmp_path / "root"
    save_cards(root / "data/kb/v7", cards, {})
    (root / "docs/eval").mkdir(parents=True)
    (root / "docs/eval/chatbot_questions_v7.json").write_text(json.dumps(QUESTIONS), encoding="utf-8")
    return root


def run(root: Path, model, *extra: str, sleeps=None) -> int:
    spec = importlib.util.spec_from_file_location("eval_chatbot", ROOT / "scripts/eval_chatbot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(["--manifest", "artifacts/gnn_embeddings_v7.json", *extra], llm_factory=lambda config: model,
                       root=root, sleep=(sleeps.append if sleeps is not None else lambda seconds: None))


class Replies(ScriptedModel):
    """Test-only stand-in: answers by question, so results can be checked."""

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        question = user.rsplit("QUESTION:", 1)[1]
        if "France" in question:
            return "I don't have that in the project outputs."
        if "hunks" in question:
            return "The top hunk is lines 207-218 [pr:o/r#30]."
        return "PR o/r#30 scored 0.765, which is correct [pr:o/r#30]."


def test_full_run_scores_saves_and_pauses_between_calls(tmp_path, capsys):
    root, model, sleeps = setup_root(tmp_path), Replies(), []
    assert run(root, model, "--pause", "3", sleeps=sleeps) == 0
    assert len(model.calls) == 3 and sleeps == [3.0, 3.0]
    assert "Q: Why is PR #30 risky?" in model.calls[1][1]                     # follow-up saw the first answer
    results = json.loads((root / "data/eval/v7/results.json").read_text(encoding="utf-8"))
    assert results["summary"]["passed"] == "3/3" and results["summary"]["correct_refusals"] == "1/1"
    assert "| a | Why is PR #30 risky? | yes | 100% | yes | yes |" in (root / "data/eval/v7/results.md").read_text(
        encoding="utf-8")


def test_saved_answers_are_reused_and_fresh_asks_again(tmp_path):
    root = setup_root(tmp_path)
    assert run(root, Replies()) == 0
    again = Replies()
    assert run(root, again) == 0 and again.calls == []                         # everything already answered
    fresh = Replies()
    assert run(root, fresh, "--fresh") == 0 and len(fresh.calls) == 3


class FailsOnSecond(Replies):
    def complete(self, system: str, user: str) -> str:
        if len(self.calls) == 1:
            raise LLMError("Groq rate limit reached (429).", "rate")
        return super().complete(system, user)


def test_a_stopped_run_continues_where_it_stopped(tmp_path, capsys):
    root = setup_root(tmp_path)
    assert run(root, FailsOnSecond()) == 1
    assert "run again to continue" in capsys.readouterr().out
    rest = Replies()
    assert run(root, rest) == 0 and len(rest.calls) == 2                       # only b and c were asked


def test_redo_asks_only_the_named_questions_again(tmp_path, capsys):
    root = setup_root(tmp_path)
    assert run(root, Replies()) == 0
    again = Replies()
    assert run(root, again, "--redo", "c") == 0
    assert len(again.calls) == 1 and "France" in again.calls[0][1]
    lines = (root / "data/eval/v7/answers.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3                                                      # replaced, not duplicated
    assert run(root, Replies(), "--redo", "zz") == 2 and "Unknown question id(s): zz" in capsys.readouterr().out


def test_retrieval_only_needs_no_language_model(tmp_path, capsys):
    root = setup_root(tmp_path)

    class NoCalls(ScriptedModel):
        def complete(self, system, user):
            raise AssertionError("must not be called")

    assert run(root, NoCalls(), "--retrieval-only") == 0
    assert "Retrieval hit rate: 100% (3 questions)" in capsys.readouterr().out


# --- the real question set ----------------------------------------------------------------------

def test_project_question_set_is_valid_and_matches_the_knowledge_base():
    questions = load_questions(ROOT / "docs/eval/chatbot_questions_v3.json")
    assert len(questions) == 15 and sum(1 for item in questions if item.get("refuse")) == 2
    kb = ROOT / "data/kb/v3/cards.jsonl"
    if not kb.is_file():
        pytest.skip("v3 knowledge base not built on this machine")
    ids = {card.id for card in load_cards(kb)}
    assert all(card in ids for item in questions for card in item["expect_cards"])
    assert all(row["retrieval"] for row in retrieval_only(questions, Retriever(load_cards(kb)), top_k=6))
