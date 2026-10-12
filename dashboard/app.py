"""AI Architecture Guardian dashboard.

    streamlit run dashboard/app.py

Three tabs: Overview (model results, dataset, test risk scores), PR explorer (one PR's score
and its XAI layers A, B, C) and Chat (the grounded chatbot).

Editing guide
  * Look and wording: change the SETTINGS block right below (title, texts, colours, sizes).
  * Theme (light/dark, fonts): .streamlit/config.toml.
  * Data: only through src.rag.api.Chatbot (list_prs, pr_details, model_metrics,
    dataset_summary, predictions, ask). Do not read the data folders directly here, so the
    dashboard can never change or break the pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(os.environ.get("GUARDIAN_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import data as views  # noqa: E402
from src.rag.api import Chatbot  # noqa: E402
from src.rag.llm import LLMError  # noqa: E402

# ============================== SETTINGS: safe to edit ==============================
TITLE = "AI Architecture Guardian"
SUBTITLE = ("Predicts whether a merged Python PR touches code that will need an architectural refactor "
            "within six months, and explains why.")
TAB_NAMES = ("Overview", "PR explorer", "Ask the chatbot")
TOP_HUNKS = 10            # rows in the layer B table
TOP_FILES = 10            # bars in the layer C chart
BAR_SIZE = 14             # bar thickness in pixels
# Colours were checked for colour-blind safety and contrast (light and dark): keep each pair together.
COLORS = {
    "light": {"safe": "#2a78d6", "risky": "#eb6834", "touched": "#2a78d6", "not touched": "#eb6834",
              "down": "#2a78d6", "up": "#e34948", "ink": "#52514e"},
    "dark": {"safe": "#3987e5", "risky": "#d95926", "touched": "#3987e5", "not touched": "#d95926",
             "down": "#3987e5", "up": "#e66767", "ink": "#c3c2b7"},
}
# ====================================================================================


def palette() -> dict[str, str]:
    theme = getattr(getattr(st, "context", None), "theme", None)
    mode = getattr(theme, "type", None) or "light"
    return COLORS.get(mode, COLORS["light"])


def available_versions() -> list[str]:
    return sorted((path.name for path in (ROOT / "data/kb").glob("v*") if (path / "cards.jsonl").is_file()),
                  key=lambda name: int(name[1:]) if name[1:].isdigit() else 0, reverse=True)


class _NoModel:
    """Placeholder so browsing works without a Groq key; the chat tab builds the real client."""
    name = "not loaded"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - never used for answers
        raise LLMError("The chatbot model is not loaded.")


@st.cache_resource(show_spinner=False)
def browser(version: str, root: str) -> Chatbot:
    """Read-only access to the cards and outputs (no language model needed)."""
    return Chatbot.from_version(version, llm=_NoModel(), root=Path(root))


def chat_bot(version: str) -> Chatbot:
    """One chatbot per browser session, so conversations do not mix."""
    key = f"bot::{version}"
    if key not in st.session_state:
        st.session_state[key] = Chatbot.from_version(version, root=ROOT, llm_factory=st.session_state.get("llm_factory"))
    return st.session_state[key]


def bar_chart(frame: pd.DataFrame, x: str, y: str, color: str, domain: list[str], colors: list[str],
              tooltip: list[str], title: str, rule: float | None = None) -> alt.Chart:
    bars = alt.Chart(frame).mark_bar(size=BAR_SIZE, cornerRadiusEnd=4).encode(
        x=alt.X(f"{x}:Q", title=title),
        y=alt.Y(f"{y}:N", sort=None, title=None, axis=alt.Axis(labelLimit=320)),
        color=alt.Color(f"{color}:N", scale=alt.Scale(domain=domain, range=colors),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=tooltip).properties(height=alt.Step(BAR_SIZE + 10))    # one fixed-height row per bar
    if rule is None:
        return bars
    line = alt.Chart(pd.DataFrame({"value": [rule]})).mark_rule(strokeDash=[4, 4], color=palette()["ink"]).encode(
        x="value:Q")
    return bars + line


# --- page ----------------------------------------------------------------------------------------

st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)
st.caption(SUBTITLE)

versions = available_versions()
if not versions:
    st.error("No knowledge base found. Run: python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v3.json")
    st.stop()
with st.sidebar:
    version = st.selectbox("Data version", versions)
    st.caption("Everything shown comes from the project's output files for this version.")

bot = browser(version, str(ROOT))
metrics = bot.model_metrics()
summary = bot.dataset_summary()
predictions = bot.predictions()
head = views.headline(metrics)
threshold = head.get("threshold", 0.5)
colors = palette()

overview, explorer, chat = st.tabs(list(TAB_NAMES))

# --- Overview --------------------------------------------------------------------------------------
with overview:
    tiles = st.columns(4)
    tiles[0].metric("PRs in the dataset", summary.get("count", len(bot.list_prs())))
    tiles[1].metric("Test PRs", head.get("test_prs", "–"))
    if head:
        for tile, label, mine, base in ((tiles[2], "Fusion test F1", head["fusion_f1"], head["baseline_f1"]),
                                        (tiles[3], "Fusion test PR-AUC", head["fusion_ap"], head["baseline_ap"])):
            gap = mine - base
            # No arrow for a zero difference: an arrow would suggest a change that is not there.
            tile.metric(label, f"{mine:.3f}", f"{gap:+.3f} vs always-risky" if abs(gap) >= 0.0005 else None)
        st.caption(f"Always-risky baseline (calls every PR risky): F1 {head['baseline_f1']:.3f}, "
                   f"PR-AUC {head['baseline_ap']:.3f}.")
    for warning in metrics.get("warnings", []):
        st.warning(warning)

    st.subheader("Model results on the test split")
    st.caption("Threshold picked on validation (best F1). Ranges are bootstrap 95% ranges: with few test PRs, "
               "read the ranges, not single numbers.")
    st.dataframe(pd.DataFrame(views.results_table(metrics)), hide_index=True, width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Risk score of every test PR")
        scores = pd.DataFrame(views.score_rows(predictions, "test", threshold))
        if not scores.empty:
            st.altair_chart(bar_chart(scores, "Risk score", "PR", "True label", ["safe (0)", "risky (1)"],
                                      [colors["safe"], colors["risky"]],
                                      ["sample_id", "Risk score", "True label", "Prediction", "Correct"],
                                      f"Fusion risk score (dashed line = threshold {threshold:.3f})", rule=threshold),
                            width="stretch")
            with st.expander("Table view"):
                st.dataframe(scores.drop(columns=["PR"]), hide_index=True, width="stretch")
    with right:
        st.subheader("Dataset")
        st.dataframe(pd.DataFrame(views.split_rows(summary)), hide_index=True, width="stretch")
        if summary.get("purged"):
            st.caption(f"{len(summary['purged'])} PRs were purged because their six-month outcome window crosses "
                       f"a split cutoff: " + ", ".join(f"#{pr.split('#')[-1]}" for pr in summary["purged"]))

# --- PR explorer ---------------------------------------------------------------------------------
with explorer:
    prs = sorted(bot.list_prs(), key=lambda meta: (not meta.get("explained"), meta["split"] != "test",
                                                   -meta["probability"]))
    only_explained = st.checkbox("Only PRs with explanations", value=True)
    choices = [meta for meta in prs if meta.get("explained") or not only_explained]
    if not choices:
        st.info("No explained PRs yet. Run: python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_<v>.json")
    else:
        chosen = st.selectbox("Pull request", choices, format_func=lambda meta: views.pr_label(meta, threshold))
        details = bot.pr_details(chosen["sample_id"])
        correct = int(details["probability"] >= threshold) == details["label"]
        cols = st.columns(4)
        cols[0].metric("Fusion risk score", f"{details['probability']:.3f}")
        cols[1].metric("Threshold", f"{threshold:.3f}")
        cols[2].metric("True label", "risky (1)" if details["label"] else "safe (0)")
        cols[3].metric("Prediction", "correct" if correct else "WRONG")
        with st.expander("Everything the chatbot knows about this PR"):
            st.text(details["card"])

        explanation = details.get("explanation")
        if not explanation:
            st.info("This PR has no XAI explanation yet. Run explain_prs.py with --split all to add it.")
        else:
            st.subheader("Layer A · structure vs diff")
            st.caption("How much each input moved the score (logit units). They add up: base + structure + diff.")
            parts = pd.DataFrame(views.layer_a_rows(explanation))
            st.altair_chart(bar_chart(parts, "Logit", "Part", "Direction", ["pushes risk down", "pushes risk up"],
                                      [colors["down"], colors["up"]], ["Part", "Logit", "Direction"], "Logit"),
                            width="stretch")

            st.subheader("Layer B · which diff hunks mattered")
            st.caption("Each hunk was hidden and the PR re-scored. Positive = this hunk pushed the risk up.")
            hunks = views.layer_b_rows(explanation, TOP_HUNKS)
            if hunks:
                st.dataframe(pd.DataFrame(hunks).drop(columns=["snippet"]), hide_index=True, width="stretch")
                for hunk in hunks[:3]:
                    label = f"{hunk['File']} lines {hunk['Lines']} (effect {hunk['Effect on risk']:+.4f})"
                    with st.expander(label.replace("_", "\\_")):          # keep __init__ from turning bold
                        st.code(hunk["snippet"] or "(no changed lines)", language="diff")
            else:
                st.caption("No hunks in analysed files.")

            graph = explanation.get("graph")
            st.subheader("Layer C · which code files mattered")
            if graph:
                st.caption(f"Integrated Gradients on the GNN. Touched files total {graph['touched_files_total']:+.2f}, "
                           f"untouched files total {graph['untouched_files_total']:+.2f}.")
                files = pd.DataFrame(views.layer_c_rows(explanation, TOP_FILES))
                st.altair_chart(bar_chart(files, "Effect", "File", "Touched by PR", ["touched", "not touched"],
                                          [colors["touched"], colors["not touched"]],
                                          ["File", "Effect", "Touched by PR", "Nodes"], "Effect on the structure score"),
                                width="stretch")
            else:
                st.caption("Layer C was skipped for this PR (run explain_prs.py without --no-graph).")
            st.caption(explanation.get("note", ""))

# --- Chat -------------------------------------------------------------------------------------------
with chat:
    st.caption("Answers come only from the project's outputs and cite their sources. "
               "Free Groq limits allow about 2–3 questions a minute.")
    history_key = f"chat::{version}"
    history = st.session_state.setdefault(history_key, [])
    if st.button("New conversation"):
        history.clear()
        if f"bot::{version}" in st.session_state:
            st.session_state[f"bot::{version}"].reset()
    for entry in history:
        with st.chat_message(entry["role"]):
            st.markdown(entry["text"])
            for line in entry.get("extra", []):
                st.caption(line)
    question = st.chat_input("Ask about a PR, the model, the data or the method…")
    if question:
        history.append({"role": "user", "text": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Thinking…"):
                    answer = chat_bot(version).ask(question)
            except (LLMError, FileNotFoundError, ValueError) as exc:
                st.error(str(exc))
                history.append({"role": "assistant", "text": f"(no answer) {exc}"})
            else:
                extra = ["Sources: " + (", ".join(card["id"] for card in answer.cards) or "none")]
                if answer.note:
                    extra.append(f"Note: {answer.note}")
                if answer.unsupported_numbers:
                    extra.append("⚠ Numbers not found in the sources: " + ", ".join(answer.unsupported_numbers))
                if answer.unknown_citations:
                    extra.append("⚠ Cites cards it was not given: " + ", ".join(answer.unknown_citations))
                st.markdown(answer.text)
                for line in extra:
                    st.caption(line)
                history.append({"role": "assistant", "text": answer.text, "extra": extra})
