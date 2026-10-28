"""Chatbot: retrieval, grounding checks, the Groq client and the chat script.

No test calls the real Groq API by default (tests must work offline and never use up the
free quota). The Groq HTTP calls are checked with httpx's built-in MockTransport. The real
model is exercised by running scripts/chat.py, or by this file's last test when
RUN_GROQ_LIVE=1 is set and GROQ_API_KEY is in .env.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import httpx
import pytest

from src.rag.answer import SYSTEM_PROMPT, build_user_message, check_answer
from src.rag.api import Chatbot
from src.rag.knowledge import build_cards, load_inputs, save_cards
from src.rag.llm import FallbackChat, GroqChat, LLMError, list_models
from src.rag.retrieval import Retriever, mentioned_pr_numbers
from tests.test_knowledge import make_project

ROOT = Path(__file__).resolve().parents[1]


def project_cards(tmp_path: Path):
    paths = make_project(tmp_path, explained=("o/r#30", "o/r#31"))
    inputs = load_inputs(manifest_path=paths["manifest"], fusion_dir=paths["fusion"], xai_dir=paths["xai"],
                         samples_dir=paths["samples"], gnn_metrics_path=paths["gnn_metrics"])
    return build_cards(inputs, paths["docs"]), paths


class ScriptedModel:
    """Test-only stand-in for Groq: returns a fixed reply and records what it was sent."""
    name = "scripted"

    def __init__(self, reply: str = "PR o/r#30 scored 0.765 [pr:o/r#30].") -> None:
        self.reply, self.calls = reply, []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


# --- retrieval ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, numbers", [("Why is PR #5331 risky?", [5331]), ("tell me about pr 5331", [5331]),
                                           ("pallets/flask#5648 and #4997", [5648, 4997]),
                                           ("what is F1 0.75 for 2 models", [])])
def test_pr_numbers_are_found_in_questions(text, numbers):
    assert mentioned_pr_numbers(text) == numbers


def test_a_mentioned_pr_is_always_retrieved_first(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why did #31 get this score?", k=3)
    assert hits[0].card.id == "pr:o/r#31" and hits[0].reason == "pr-number"


def test_topic_words_bring_the_model_and_dataset_cards(tmp_path):
    cards, _ = project_cards(tmp_path)
    retriever = Retriever(cards)
    assert retriever.retrieve("How good is the model compared to the baseline?", k=3)[0].card.id == "model:fusion"
    assert retriever.retrieve("How many PRs were purged?", k=3)[0].card.id == "dataset"
    assert retriever.retrieve("Which PRs were false positives?", k=3)[0].card.id == "predictions:test"


@pytest.mark.parametrize("question, card_id", [
    ("How well does the fusion model do on the test split?", "model:fusion"),
    ("Is fusion better than CodeReviewer?", "model:fusion"),
    ("Which repositories are in the data?", "dataset"),
    ("Did the GNN learn a shortcut like the merge date?", "model:shortcuts"),
])
def test_everyday_wordings_bring_the_right_card(tmp_path, question, card_id):
    from tests.test_knowledge import holdout_gnn_metrics
    paths = make_project(tmp_path, explained=("o/r#30",))
    holdout_gnn_metrics(paths["gnn_metrics"])
    inputs = load_inputs(manifest_path=paths["manifest"], fusion_dir=paths["fusion"], xai_dir=paths["xai"],
                         samples_dir=paths["samples"], gnn_metrics_path=paths["gnn_metrics"])
    cards = build_cards(inputs, paths["docs"])
    ids = [hit.card.id for hit in Retriever(cards).retrieve(question, k=6)]
    assert card_id in ids


def test_a_general_question_gets_at_most_one_example_pr_and_finds_notes_by_file_title(tmp_path):
    cards, _ = project_cards(tmp_path)
    for card in cards:
        if card.kind == "doc":
            card.meta["section"] = "Limitations"
    hits = Retriever(cards).retrieve("What are the limitations of risky prs?", k=6)
    assert sum(hit.card.kind == "pr" for hit in hits) <= 1
    assert any(hit.card.kind == "doc" for hit in hits)


def test_topic_words_match_whole_words_only(tmp_path):
    cards, _ = project_cards(tmp_path)
    ids = [hit.card.id for hit in Retriever(cards).retrieve("Can you update me?", k=6)]
    assert "model:shortcuts" not in ids


def test_prediction_tables_follow_the_split_in_the_question(tmp_path):
    cards, _ = project_cards(tmp_path)
    retriever = Retriever(cards)
    assert retriever.retrieve("Which validation PRs were wrong?", k=3)[0].card.id == "predictions:validation"
    ids = [hit.card.id for hit in retriever.retrieve("What does layer B do?", k=6)]
    assert not any(card_id.startswith("predictions:") for card_id in ids)      # big tables only when asked


def test_a_named_pr_brings_no_unrelated_pr_cards(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why was PR #30 flagged as risky?", k=6)
    assert hits[0].card.id == "pr:o/r#30"
    assert [hit.card.id for hit in hits if hit.card.kind == "pr"] == ["pr:o/r#30"]


def test_prompt_says_to_start_with_layer_a_and_not_to_credit_the_refactor_to_the_pr():
    assert "start with layer A" in SYSTEM_PROMPT and "Negative values push the risk down" in SYSTEM_PROMPT
    assert "reviewer's note describes the later refactor PR" in SYSTEM_PROMPT


def test_a_named_pr_gets_only_two_extra_cards(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=6)
    assert hits[0].card.id == "pr:o/r#30" and len(hits) <= 3


def test_previous_pr_is_reused_only_for_follow_up_questions(tmp_path):
    cards, _ = project_cards(tmp_path)
    retriever = Retriever(cards)
    assert retriever.retrieve("and which hunks mattered?", k=3, context_prs=[30])[0].card.id == "pr:o/r#30"
    unrelated = retriever.retrieve("What is the capital of France?", k=3, context_prs=[30])
    assert all(hit.card.id != "pr:o/r#30" for hit in unrelated)


def test_keyword_search_finds_method_notes_and_is_deterministic(tmp_path):
    cards, _ = project_cards(tmp_path)
    retriever = Retriever(cards)
    first = [hit.card.id for hit in retriever.retrieve("hides one hunk at a time", k=4)]
    assert first[0] == "doc:xai#layer-b"
    assert first == [hit.card.id for hit in Retriever(cards).retrieve("hides one hunk at a time", k=4)]


# --- grounding checks ------------------------------------------------------------------------

def test_answer_with_real_numbers_and_known_citations_is_grounded(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=4)
    answer = check_answer("Why is PR #30 risky?", "It scored 0.765 [pr:o/r#30], structure -0.28 and "
                          "src/pkg/cli.py +1.46 (76.5% is not a probability) [pr:o/r#30].", hits)
    assert answer.grounded and answer.citations == ["pr:o/r#30"]


def test_invented_numbers_and_unknown_citations_are_flagged(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=2)
    answer = check_answer("Why is PR #30 risky?", "It scored 0.912 with recall 87.3% [model:other].", hits)
    assert not answer.grounded
    assert answer.unsupported_numbers == ["0.912", "87.3%"] and answer.unknown_citations == ["model:other"]


def test_citations_in_full_width_brackets_are_checked(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=2)
    answer = check_answer("q", "Scored 0.765 \u3010pr:o/r#30\u3011 and \u3010model:other\u3011.", hits)
    assert answer.citations == ["pr:o/r#30", "model:other"] and answer.unknown_citations == ["model:other"]
    assert "[pr:o/r#30]" in answer.text


def test_line_ranges_and_unicode_dashes_are_not_false_alarms(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=2)            # card says "lines 207-218"
    for text in ("The top hunk is lines 207-218 [pr:o/r#30].", "The top hunk is lines 207\u2011218 [pr:o/r#30].",
                 "Structure \u22120.28 [pr:o/r#30]."):
        assert check_answer("q", text, hits).grounded, text


def test_prompt_contains_rules_cards_and_recent_history(tmp_path):
    cards, _ = project_cards(tmp_path)
    hits = Retriever(cards).retrieve("Why is PR #30 risky?", k=2)
    message = build_user_message("Why is PR #30 risky?", hits, history=[("old q", "old a")] * 3)
    assert message.startswith("CARDS:\n\n[pr:o/r#30]") and message.endswith("QUESTION: Why is PR #30 risky?")
    assert message.count("Q: old q") == 2                                     # only the last two turns
    assert "Answer ONLY from the cards" in SYSTEM_PROMPT and "not calibrated probabilities" in SYSTEM_PROMPT
    assert "true label" in SYSTEM_PROMPT and "correct or wrong" in SYSTEM_PROMPT and "Do not guess" in SYSTEM_PROMPT


# --- Groq client (HTTP mocked with httpx.MockTransport) -------------------------------------------

def groq_with(handler, **extra) -> GroqChat:
    return GroqChat("llama-3.3-70b-versatile", api_key="test-key",
                    client=httpx.Client(transport=httpx.MockTransport(handler)), **extra)


def test_groq_request_and_reply(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hello  "}}]})

    model = groq_with(handler, options={"reasoning_effort": "low", "include_reasoning": False})
    assert model.complete("system text", "user text") == "hello"
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "llama-3.3-70b-versatile" and seen["body"]["temperature"] == 0.0
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["include_reasoning"] is False
    assert [message["role"] for message in seen["body"]["messages"]] == ["system", "user"]


def test_groq_retries_after_rate_limit(monkeypatch):
    monkeypatch.setattr("src.rag.llm.time.sleep", lambda seconds: None)
    replies = iter([httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"message": "slow down"}}),
                    httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})])
    assert groq_with(lambda request: next(replies)).complete("s", "u") == "ok"


@pytest.mark.parametrize("status, body, message", [
    (401, {"error": {"message": "Invalid API Key"}}, "Check GROQ_API_KEY"),
    (404, {"error": {"message": "The model does not exist"}}, "--list-models"),
    (429, {"error": {"message": "Rate limit"}}, "rate limit"),
])
def test_groq_errors_explain_what_to_do(monkeypatch, status, body, message):
    monkeypatch.setattr("src.rag.llm.time.sleep", lambda seconds: None)
    with pytest.raises(LLMError, match=message):
        groq_with(lambda request: httpx.Response(status, json=body), retries=0).complete("s", "u")


def test_reasoning_in_think_tags_is_removed_and_empty_answers_explained():
    reply = lambda content: (lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))  # noqa: E731
    assert groq_with(reply("<think>step 1\nstep 2</think>\nThe answer.")).complete("s", "u") == "The answer."
    with pytest.raises(LLMError, match="empty answer"):
        groq_with(reply("<think>only thinking</think>")).complete("s", "u")


class FailingModel:
    def __init__(self, name: str, kind: str) -> None:
        self.name, self.kind = name, kind

    def complete(self, system: str, user: str) -> str:
        raise LLMError("primary failed", self.kind)


@pytest.mark.parametrize("kind, reason", [("model", "is not available to this key"), ("rate", "is rate-limited")])
def test_fallback_model_answers_when_the_main_model_cannot(kind, reason):
    chat = FallbackChat(FailingModel("big-model", kind), ScriptedModel("from fallback"))
    assert chat.complete("s", "u") == "from fallback"
    assert chat.last_used == "scripted" and reason in chat.note


def test_fallback_is_not_used_for_a_bad_key():
    with pytest.raises(LLMError, match="primary failed"):
        FallbackChat(FailingModel("big-model", "auth"), ScriptedModel()).complete("s", "u")


def test_list_models_returns_sorted_ids():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-20b"}, {"id": "a/model"}]})))
    assert list_models(api_key="k", client=client) == ["a/model", "openai/gpt-oss-20b"]


def test_missing_key_is_explained(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GROQ_API_KEY is not set"):
        GroqChat("llama-3.3-70b-versatile")


# --- the chatbot API and the chat script ------------------------------------------------------------

def test_chatbot_answers_from_cards_and_remembers_the_pr_for_follow_ups(tmp_path):
    cards, _ = project_cards(tmp_path)
    model = ScriptedModel()
    bot = Chatbot(cards, model, top_k=3)
    first = bot.ask("Why is PR #30 risky?")
    assert first.grounded and first.citations == ["pr:o/r#30"] and first.cards[0]["reason"] == "pr-number"
    bot.ask("And what were its top files?")                                   # no number: same PR as before
    assert "[pr:o/r#30]" in model.calls[-1][1] and "Q: Why is PR #30 risky?" in model.calls[-1][1]
    bot.reset()
    bot.ask("And what were its top files?")
    assert "Q: Why is PR #30 risky?" not in model.calls[-1][1]


def test_chatbot_gives_ui_data_without_the_language_model(tmp_path):
    cards, paths = project_cards(tmp_path)
    root = tmp_path / "root"
    (root / "data/xai/v7").mkdir(parents=True)
    (root / "data/xai/v7/o__r__30.json").write_bytes((paths["xai"] / "o__r__30.json").read_bytes())
    bot = Chatbot(cards, ScriptedModel(), version="v7", root=root)
    assert {row["sample_id"] for row in bot.list_prs()} == {"o/r#10", "o/r#11", "o/r#20", "o/r#21", "o/r#30",
                                                           "o/r#31", "o/r#32"}
    details = bot.pr_details("o/r#30")
    assert details["explanation"]["graph"]["files"][0]["file"] == "src/pkg/a.py" and details["label"] == 1
    assert "Always risky (baseline)" in bot.model_summary()
    with pytest.raises(KeyError):
        bot.pr_details("o/r#999")


def run_chat(tmp_path: Path, *argv: str, reply: str = "PR o/r#30 scored 0.765 [pr:o/r#30].", inputs=()):
    cards, _ = project_cards(tmp_path / "project")
    save_cards(tmp_path / "root/data/kb/v7", cards, {})
    spec = importlib.util.spec_from_file_location("chat", ROOT / "scripts/chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    answers = iter(inputs)
    return module.main(["--manifest", "artifacts/gnn_embeddings_v7.json", *argv],
                       llm_factory=lambda config: ScriptedModel(reply), read=lambda prompt: next(answers),
                       root=tmp_path / "root")


def test_chat_script_one_question_prints_answer_and_sources(tmp_path, capsys):
    assert run_chat(tmp_path, "-q", "Why is PR #30 risky?") == 0
    printed = capsys.readouterr().out
    assert "Bot: PR o/r#30 scored 0.765 [pr:o/r#30]." in printed and "Sources: pr:o/r#30 (pr-number)" in printed
    assert "WARNING" not in printed


def test_chat_script_warns_about_numbers_not_in_the_cards(tmp_path, capsys):
    assert run_chat(tmp_path, "-q", "Why is PR #30 risky?", reply="It scored 0.912 [pr:o/r#30].") == 0
    assert "WARNING: these numbers are not in the source cards, double-check them: 0.912" in capsys.readouterr().out


def test_chat_script_interactive_loop(tmp_path, capsys):
    assert run_chat(tmp_path, inputs=["Why is PR #30 risky?", "reset", "exit"]) == 0
    printed = capsys.readouterr().out
    assert printed.count("Bot: ") == 1 and "Conversation cleared." in printed


def test_chat_script_lists_models_and_marks_the_configured_ones(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("chat", ROOT / "scripts/chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/chatbot.json").write_text(json.dumps({"model": "openai/gpt-oss-120b",
                                                              "fallback_model": "gone/model"}), encoding="utf-8")
    assert module.main(["--list-models"], root=tmp_path,
                       models_lister=lambda: ["openai/gpt-oss-120b", "whisper-large-v3"]) == 0
    printed = capsys.readouterr().out
    assert " * openai/gpt-oss-120b" in printed and "   whisper-large-v3" in printed
    assert "Not available to this key: gone/model" in printed


def test_chat_script_shows_when_the_fallback_answered(tmp_path, capsys):
    cards, _ = project_cards(tmp_path / "project")
    save_cards(tmp_path / "root/data/kb/v7", cards, {})
    spec = importlib.util.spec_from_file_location("chat", ROOT / "scripts/chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = lambda config: FallbackChat(FailingModel("big-model", "model"), ScriptedModel("PR o/r#30 [pr:o/r#30]."))  # noqa: E731
    assert module.main(["--manifest", "artifacts/gnn_embeddings_v7.json", "-q", "Why #30?"], llm_factory=factory,
                       root=tmp_path / "root") == 0
    assert "Note: big-model is not available to this key; answered with scripted." in capsys.readouterr().out


def test_chat_script_explains_a_missing_knowledge_base(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("chat", ROOT / "scripts/chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--manifest", "artifacts/gnn_embeddings_v7.json", "-q", "hi"],
                       llm_factory=lambda config: ScriptedModel(), root=tmp_path) == 2
    assert "build_kb.py" in capsys.readouterr().out


# --- optional: one real Groq call --------------------------------------------------------------------

def test_live_groq_answer_is_grounded():
    if os.environ.get("RUN_GROQ_LIVE") != "1":
        pytest.skip("set RUN_GROQ_LIVE=1 to call the real Groq API")
    if not (ROOT / "data/kb/v3/cards.jsonl").is_file():
        pytest.skip("build the v3 knowledge base first")
    bot = Chatbot.from_version("v3")
    answer = bot.ask("What was the fusion risk score of PR #5648, and was the prediction correct?")
    assert "pr:pallets/flask#5648" in answer.citations and not answer.unknown_citations


def test_chat_script_says_none_when_no_card_was_used(tmp_path, capsys):
    assert run_chat(tmp_path, "-q", "What is the capital of France?",
                    reply="I don't have that in the project outputs.") == 0
    assert "Sources: none" in capsys.readouterr().out
