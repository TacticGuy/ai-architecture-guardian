"""Dashboard: the table helpers, and a headless run of the real app on test data (no Groq calls)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dashboard import data as views
from src.rag.api import Chatbot
from src.rag.knowledge import build_cards, load_inputs, save_cards
from tests.test_chatbot import ScriptedModel
from tests.test_knowledge import make_project

ROOT = Path(__file__).resolve().parents[1]


def project_root(tmp_path: Path) -> Path:
    """A folder laid out like the real project: data/kb, data/fusion, data/xai for version v7."""
    paths = make_project(tmp_path / "project", explained=("o/r#30", "o/r#31"))
    inputs = load_inputs(manifest_path=paths["manifest"], fusion_dir=paths["fusion"], xai_dir=paths["xai"],
                         samples_dir=paths["samples"], gnn_metrics_path=paths["gnn_metrics"])
    root = tmp_path / "root"
    save_cards(root / "data/kb/v7", build_cards(inputs, paths["docs"]), {})
    shutil.copytree(paths["fusion"], root / "data/fusion/v7")
    shutil.copytree(paths["xai"], root / "data/xai/v7")
    return root


# --- table helpers ------------------------------------------------------------------------------

def test_tables_are_built_from_the_chat_api(tmp_path):
    bot = Chatbot.from_version("v7", llm=ScriptedModel(), root=project_root(tmp_path))
    metrics = bot.model_metrics()
    rows = views.results_table(metrics)
    assert [row["Model"] for row in rows] == ["Always risky (baseline)", "GNN only", "CodeReviewer only", "Fusion"]
    assert rows[0]["F1 range"] == "0.50–0.93"
    head = views.headline(metrics)
    assert head["threshold"] == 0.5 and head["fusion_ap"] == 0.577
    splits = views.split_rows(bot.dataset_summary())
    assert [row["Split"] for row in splits] == ["train", "validation", "test"]
    assert splits[2] == {"Split": "test", "PRs": 3, "Risky (1)": 1, "Safe (0)": 2}


def test_scores_are_sorted_and_marked_correct_or_wrong(tmp_path):
    bot = Chatbot.from_version("v7", llm=ScriptedModel(), root=project_root(tmp_path))
    rows = views.score_rows(bot.predictions(), "test", 0.5)
    assert [row["PR"] for row in rows] == ["#30", "#32", "#31"]
    assert rows[1]["True label"] == "safe (0)" and rows[1]["Correct"] == "no"     # 0.6 >= 0.5 but safe


def test_explanation_rows_for_the_three_layers(tmp_path):
    bot = Chatbot.from_version("v7", llm=ScriptedModel(), root=project_root(tmp_path))
    explanation = bot.pr_details("o/r#30")["explanation"]
    assert [row["Direction"] for row in views.layer_a_rows(explanation)] == ["pushes risk up", "pushes risk down",
                                                                            "pushes risk up"]
    hunk = views.layer_b_rows(explanation)[0]
    assert hunk["Lines"] == "207-218" and hunk["snippet"] == "-import warnings\n+x = 1"
    assert [row["Touched by PR"] for row in views.layer_c_rows(explanation)] == ["touched", "not touched"]
    meta = next(meta for meta in bot.list_prs() if meta["sample_id"] == "o/r#32")
    assert views.pr_label(meta, 0.5) == "#32 · test · safe · risk 0.600 · WRONG"


def test_dataset_summary_lists_purged_prs_and_cutoffs(tmp_path):
    summary = Chatbot.from_version("v7", llm=ScriptedModel(), root=project_root(tmp_path)).dataset_summary()
    assert summary["purged"] == ["o/r#5", "o/r#25"] and summary["cutoffs"]["train"].startswith("2021-05-05")


# --- the real app, headless -------------------------------------------------------------------------

def pr_picker(app):
    return next(box for box in app.selectbox if box.label == "Pull request")


@pytest.fixture
def app(tmp_path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("GUARDIAN_ROOT", str(project_root(tmp_path)))
    return testing.AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=60)


def test_all_tabs_render_without_errors(app):
    app.run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Overview", "PR explorer", "Ask the chatbot"]
    assert app.metric[0].value == "7"                                          # PRs in the dataset
    f1_tile = next(metric for metric in app.metric if metric.label == "Fusion test F1")
    assert f1_tile.value == "0.750" and not f1_tile.delta                     # same as baseline: no arrow
    assert any("Fusion" in str(frame.value) for frame in app.dataframe)
    picker = pr_picker(app)
    assert picker.options[0].startswith("#30 · test · risky")             # explained PRs first, highest score
    assert len(picker.options) == 2                                        # only explained PRs by default
    assert any(metric.value == "correct" for metric in app.metric)
    assert any("Layer C" in header.value for header in app.subheader)


def test_explorer_can_show_unexplained_prs_and_wrong_predictions(app):
    app.run()
    app.checkbox[0].uncheck().run()                                           # show all PRs
    picker = pr_picker(app)
    assert len(picker.options) == 7
    picker.select_index(next(i for i, text in enumerate(picker.options) if text.startswith("#32"))).run()
    assert not app.exception
    assert any(metric.value == "WRONG" for metric in app.metric)
    assert any("no XAI explanation yet" in info.value for info in app.info)


def test_chat_tab_answers_with_sources(app):
    app.session_state["llm_factory"] = lambda config: ScriptedModel("PR o/r#30 scored 0.765 [pr:o/r#30].")
    app.run()
    app.chat_input[0].set_value("Why is PR #30 risky?").run()
    assert not app.exception
    assert any("0.765" in block.value for block in app.markdown)
    assert any("Sources: pr:o/r#30" in caption.value for caption in app.caption)


def test_missing_knowledge_base_shows_how_to_build_it(tmp_path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("GUARDIAN_ROOT", str(tmp_path))
    app = testing.AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=60).run()
    assert "build_kb.py" in app.error[0].value
