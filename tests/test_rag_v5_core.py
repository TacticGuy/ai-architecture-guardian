import copy
import json
from pathlib import Path

import pytest

from src.rag_v5.generate import explain_pr
from src.rag_v5.grounding import edge_label, violations
from src.rag_v5.retrieval import load_cards, retrieve_by_signature, retrieve_by_text
from src.rag_v5.signature import TAGS, signature

FIXTURE = Path(__file__).parent / "fixtures" / "attribution_v5"


def sample(name="high_risk"):
    return json.loads((FIXTURE / f"{name}.json").read_text(encoding="utf-8"))


def test_cards_and_retrieval_are_deterministic():
    cards = load_cards()
    assert len(cards) >= 50
    sig = signature(sample())
    assert retrieve_by_signature(sig, cards) == retrieve_by_signature(sig, cards)
    assert retrieve_by_text("move CLI loading", cards) == retrieve_by_text("move CLI loading", cards)
    assert all(c["reason"] for c in retrieve_by_signature(sig, cards))


@pytest.mark.parametrize("tag,alter", [
    ("new_cycle", lambda a: a.update(pr_creates_cycle=True)),
    ("import_cycle_member", lambda a: a["module_evidence"]["flask.app"].update(in_import_cycle=True)),
    ("mutual_import", lambda a: a["top_edges"].extend([
        {"source": "a", "target": "b", "source_module": "a", "target_module": "b", "relation": "IMPORTS", "attribution": .3},
        {"source": "b", "target": "a", "source_module": "b", "target_module": "a", "relation": "IMPORTS", "attribution": .3}])),
    ("efferent_growth", lambda a: a["module_evidence"]["flask.app"].update(ce_after=12)),
    ("afferent_hub", lambda a: a["module_evidence"]["flask.app"].update(ca_after=20)),
    ("instability_rise", lambda a: a["module_evidence"]["flask.app"].update(ce_after=20)),
    ("cross_module_call", lambda a: None),
    ("added_dependency", lambda a: None),
    ("global_state", lambda a: a["top_edges"][0].update(relation="ACCESSES_GLOBAL")),
    ("inheritance_coupling", lambda a: a["top_edges"][0].update(relation="INHERITS")),
    ("god_node", lambda a: a["top_edges"].extend([
        {"source": "src/flask/app.py:flask.app.Flask", "target": str(i), "source_module": "flask.app",
         "target_module": "flask.cli", "relation": "CALLS", "attribution": .01} for i in range(15)])),
    ("feature_envy", lambda a: (a["top_nodes"][0].update(type="method", id="src/flask/app.py:flask.app.Flask.run"))),
    ("low_risk", lambda a: a.update(risk_score=.1)),
])
def test_each_signature_tag(tag, alter):
    assert tag in TAGS
    data = copy.deepcopy(sample())
    alter(data)
    assert tag in signature(data)["tags"]
    assert abs(sum(signature(data)["tags"].values()) - 1) < 1e-9


def test_low_risk_fixture():
    sig = signature(sample("low_risk"))
    assert "low_risk" in sig["tags"] and "global_state" in sig["tags"]


def test_grounding_rejects_unknown_claims():
    data = sample()
    answer = {"evidence": [{"edge": "invented", "why": "Rises by 999"}],
              "principles": ["NOT_RETRIEVED"], "explanation": "Risk is 100 percent."}
    issues = violations(answer, data, [])
    assert len(issues) >= 3


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return next(self.responses)


def test_explain_retries_then_returns_grounded_json():
    data = sample()
    good = {"verdict": "degrading", "explanation": "The changed call adds a dependency.",
            "evidence": [{"edge": edge_label(data["top_edges"][0]), "why": "It connects the touched modules."}],
            "principles": [], "suggestion": {"refactoring": "Move Function", "files": data["changed_files"][:1],
                                           "steps": ["Move the call behind a small interface."]},
            "confidence_note": "This is a model output, not a probability."}
    llm = FakeLLM(["not json", json.dumps(good)])
    result = explain_pr(data, llm=llm)
    assert result["verdict"] == "degrading"
    assert result["attempt_violations"][0]
    assert result["grounding_violations"] == []


@pytest.mark.parametrize("mode", ["signature", "text", "none"])
def test_all_modes_run_offline_with_fake_llm(mode):
    data = sample("low_risk")
    answer = {"verdict": "safe", "explanation": "The model score is below its threshold.",
              "evidence": [], "principles": [],
              "suggestion": {"refactoring": "None", "files": [], "steps": []},
              "confidence_note": "This output is not a probability."}
    llm = FakeLLM([json.dumps(answer)])
    result = explain_pr(data, mode=mode, llm=llm)
    assert result["verdict"] == "safe"
    assert result["mode"] == mode
    prompt = json.loads(llm.calls[0][1])
    assert prompt["layer_a"]["history"] == -0.1
    assert prompt["history_features"]["touched_file_commits_6m"] == 2
