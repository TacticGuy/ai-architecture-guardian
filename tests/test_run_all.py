"""run_all: step order, stopping on failure, --from/--to, missing inputs, the run log, and one full run.

The full run uses the real scripts on a small real code graph (from tests/test_xai_graph.py). Only the
CodeReviewer encoder and the Groq model are stand-ins, and only here in the tests.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from tests.test_chatbot import ScriptedModel
from tests.test_xai_graph import build_everything, fake_factory

ROOT = Path(__file__).resolve().parents[1]


def load_run_all():
    spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts/run_all.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def small_root(tmp_path: Path, questions: bool = True) -> Path:
    """Every input file run_all checks for, with placeholder content (the steps themselves are recorded, not run)."""
    root = tmp_path / "root"
    (root / "artifacts").mkdir(parents=True)
    (root / "artifacts/gnn_embeddings_v9.json").write_text(json.dumps(
        {"embedding_file": "gnn_embeddings_v9.pt", "checkpoint_name": "gnn_future_risk_v9.pt", "rows": []}),
        encoding="utf-8")
    for name in ("gnn_embeddings_v9.pt", "gnn_future_risk_v9.pt"):
        (root / "artifacts" / name).write_bytes(b"x")
    (root / "data/future_pr_samples_v9").mkdir(parents=True)
    if questions:
        (root / "docs/eval").mkdir(parents=True)
        (root / "docs/eval/chatbot_questions_v9.json").write_text("{}", encoding="utf-8")
    return root


def recording(module, monkeypatch, fail: str | None = None) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []

    def fake_run(step, argv, kwargs):
        calls.append((step, argv))
        return 1 if step == fail else 0
    monkeypatch.setattr(module, "_run", fake_run)
    return calls


def run_log(root: Path) -> list[dict]:
    return json.loads((root / "data/runs/v9/run.json").read_text(encoding="utf-8"))["runs"]


MANIFEST = ["--manifest", "artifacts/gnn_embeddings_v9.json"]


# --- the runner logic -------------------------------------------------------------------------------

def test_steps_run_in_order_with_explicit_paths(tmp_path, monkeypatch):
    module, root = load_run_all(), small_root(tmp_path)
    calls = recording(module, monkeypatch)
    assert module.main(MANIFEST, root=root) == 0
    assert [step for step, _ in calls] == ["embeddings", "fusion", "explain", "kb", "eval"]
    argv = dict(calls[:4])
    assert argv["fusion"][argv["fusion"].index("--gnn") + 1] == str(root / "artifacts/gnn_embeddings_v9.pt")
    assert argv["explain"][argv["explain"].index("--gnn-checkpoint") + 1] == str(root / "artifacts/gnn_future_risk_v9.pt")
    assert argv["explain"][argv["explain"].index("--split") + 1] == "test"
    assert calls[4][1][-1] == "--retrieval-only"                          # no Groq calls unless --with-eval


def test_first_failure_stops_the_run_and_says_how_to_continue(tmp_path, monkeypatch, capsys):
    module, root = load_run_all(), small_root(tmp_path)
    calls = recording(module, monkeypatch, fail="explain")
    assert module.main(MANIFEST, root=root) == 1
    assert [step for step, _ in calls] == ["embeddings", "fusion", "explain"]
    assert "--from explain" in capsys.readouterr().out
    last = run_log(root)[-1]
    assert last["result"] == "failed" and [step["status"] for step in last["steps"]] == ["ok", "ok", "failed"]


def test_from_and_to_pick_the_steps(tmp_path, monkeypatch):
    module, root = load_run_all(), small_root(tmp_path)
    (root / "data/embeddings/microsoft__codereviewer__gnn_embeddings_v9").mkdir(parents=True)
    (root / "data/embeddings/microsoft__codereviewer__gnn_embeddings_v9/embeddings.pt").write_bytes(b"x")
    calls = recording(module, monkeypatch)
    assert module.main(MANIFEST + ["--from", "fusion", "--to", "kb"], root=root) == 0
    assert [step for step, _ in calls] == ["fusion", "explain", "kb"]
    with pytest.raises(SystemExit):
        module.main(MANIFEST + ["--from", "kb", "--to", "fusion"], root=root)


def test_full_eval_asks_again_only_after_the_knowledge_base_was_rebuilt(tmp_path, monkeypatch):
    module, root = load_run_all(), small_root(tmp_path)
    (root / "data/fusion/v9").mkdir(parents=True)
    (root / "data/fusion/v9/fusion_model.pt").write_bytes(b"x")
    calls = recording(module, monkeypatch)
    module.main(MANIFEST + ["--from", "kb", "--with-eval"], root=root)
    assert calls[-1][0] == "eval" and "--fresh" in calls[-1][1]
    (root / "data/kb/v9").mkdir(parents=True, exist_ok=True)
    (root / "data/kb/v9/cards.jsonl").write_text("", encoding="utf-8")
    calls.clear()
    module.main(MANIFEST + ["--from", "eval", "--with-eval"], root=root)  # e.g. continuing after a Groq limit
    assert [step for step, _ in calls] == ["eval", "eval"] and "--fresh" not in calls[-1][1]


def test_eval_is_skipped_without_a_question_set(tmp_path, monkeypatch, capsys):
    module, root = load_run_all(), small_root(tmp_path, questions=False)
    calls = recording(module, monkeypatch)
    assert module.main(MANIFEST, root=root) == 0
    assert "eval" not in [step for step, _ in calls]
    assert "skipped (no question set chatbot_questions_v9.json" in capsys.readouterr().out
    assert run_log(root)[-1]["steps"][-1] == {"step": "eval", "status": "skipped", "seconds": 0}


def test_missing_inputs_are_listed_before_anything_runs(tmp_path, monkeypatch, capsys):
    module, root = load_run_all(), small_root(tmp_path)
    shutil.rmtree(root / "data/future_pr_samples_v9")
    (root / "artifacts/gnn_future_risk_v9.pt").unlink()
    calls = recording(module, monkeypatch)
    assert module.main(MANIFEST, root=root) == 2 and calls == []
    out = capsys.readouterr().out
    assert "future_pr_samples_v9" in out and "gnn_future_risk_v9.pt" in out and "--no-graph" in out
    (root / "data/future_pr_samples_v9").mkdir()
    assert module.main(MANIFEST + ["--no-graph"], root=root) == 0          # layer C skipped: no checkpoint needed
    assert "--no-graph" in dict(calls)["explain"]


def test_skipped_steps_need_their_saved_outputs(tmp_path, monkeypatch, capsys):
    module, root = load_run_all(), small_root(tmp_path)
    recording(module, monkeypatch)
    assert module.main(MANIFEST + ["--from", "explain"], root=root) == 2
    out = capsys.readouterr().out
    assert "embeddings.pt (run from 'embeddings')" in out and "fusion_model.pt (run from 'fusion')" in out


def test_manifest_needs_a_version_and_must_exist(tmp_path, monkeypatch, capsys):
    module, root = load_run_all(), small_root(tmp_path)
    recording(module, monkeypatch)
    with pytest.raises(SystemExit):
        module.main(["--manifest", "artifacts/embeddings.json"], root=root)
    assert module.main(["--manifest", "artifacts/gnn_embeddings_v4.json"], root=root) == 2
    assert "gnn_embeddings_v4.json (from the GNN teammate)" in capsys.readouterr().out


def test_run_log_keeps_the_last_50_runs_with_input_fingerprints(tmp_path, monkeypatch):
    module, root = load_run_all(), small_root(tmp_path)
    recording(module, monkeypatch)
    for _ in range(52):
        module.main(MANIFEST + ["--to", "embeddings"], root=root)
    runs = run_log(root)
    assert len(runs) == 50
    assert set(runs[-1]["inputs"]) == {"gnn_embeddings_v9.json", "gnn_embeddings_v9.pt", "gnn_future_risk_v9.pt"}
    assert runs[-1]["version"] == "v9" and runs[-1]["result"] == "ok"


# --- one full run with the real scripts -------------------------------------------------------------

class Answers(ScriptedModel):
    """Test-only stand-in for Groq."""

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "I don't have that in the project outputs." if "France" in user.rsplit("QUESTION:", 1)[1] \
            else "PR org/r#13 was explained [pr:org/r#13]."


def test_full_run_rebuilds_every_output(tmp_path, capsys):
    root = tmp_path / "root"
    build_everything(root)                                   # samples, manifest, GNN vectors and checkpoint
    (root / "data").mkdir(exist_ok=True)
    (root / "samples").rename(root / "data/future_pr_samples_v9")
    (root / "docs/eval").mkdir(parents=True)
    (root / "docs/eval/chatbot_questions_v9.json").write_text(json.dumps({"version": "v9", "questions": [
        {"id": "a", "topic": "single PR", "question": "Why is PR #13 risky?", "expect_cards": ["pr:org/r#13"],
         "must_include": [["explained"]]},
        {"id": "b", "topic": "off-topic", "question": "What is the capital of France?", "refuse": True,
         "expect_cards": [], "must_include": []}]}), encoding="utf-8")
    model = Answers()
    code = load_run_all().main(MANIFEST + ["--with-eval", "--pause", "0", "--diff-model", "fake/model"],
                               encoder_factory=fake_factory, llm_factory=lambda config: model, root=root)
    out = capsys.readouterr().out
    assert code == 0, out
    assert [line.split(":")[0] for line in out.splitlines() if line.startswith("=== ") and ": python scripts/" in line] == \
        ["=== embeddings", "=== fusion", "=== explain", "=== kb", "=== eval"]
    assert (root / "data/embeddings/fake__model__gnn_embeddings_v9/embeddings.pt").is_file()
    metrics = json.loads((root / "data/fusion/v9/metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["results"]) >= {"always_risky", "gnn_only", "codereviewer_only", "fusion"}
    report = json.loads((root / "data/xai/v9/org__r__13.json").read_text(encoding="utf-8"))
    assert report["graph"]["files"]                                       # layer C ran with the checkpoint
    assert (root / "data/kb/v9/cards.jsonl").is_file()
    results = json.loads((root / "data/eval/v9/results.json").read_text(encoding="utf-8"))
    assert results["summary"]["passed"] == "2/2" and len(model.calls) == 2
    last = run_log(root)[-1]
    assert last["result"] == "ok" and [step["step"] for step in last["steps"]] == list(load_run_all().STEPS)
