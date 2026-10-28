"""FastAPI backend for the AI Guardian web app.

    uvicorn api.main:app --reload --port 8000

It exposes the same data the former Streamlit dashboard showed (model results, PR explorer with XAI
layers A, B and C, live GitHub PR analysis and the grounded chatbot). All logic is reused:
  * data: src.rag.api.Chatbot (read-only browsing, no language model needed)
  * table shaping: api.views
  * live PR scoring: src.live_pr.analyze_live_pr
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api import views
from src.live_pr import LivePRError, analyze_live_pr
from src.rag.api import Chatbot
from src.rag.llm import LLMError

TOP_HUNKS, TOP_FILES = 10, 10


class _NoModel:
    """Placeholder so browsing works without a Groq key."""
    name = "not loaded"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - never used for answers
        raise LLMError("The chatbot model is not loaded.")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=100)
    version: str | None = None


class ResetRequest(BaseModel):
    session_id: str = Field(default="default", max_length=100)
    version: str | None = None


class LiveRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    max_hunks: int = Field(default=3, ge=0, le=5)
    version: str | None = None


def create_app(root: Path | None = None, llm_factory: Any = None) -> FastAPI:
    root = Path(root or os.environ.get("GUARDIAN_ROOT", Path(__file__).resolve().parents[1]))
    app = FastAPI(title="AI Guardian API")
    sessions: dict[str, Chatbot] = {}

    def versions() -> list[str]:
        found = (path.name for path in (root / "data/kb").glob("v*") if (path / "cards.jsonl").is_file())
        return sorted(found, key=lambda name: int(name[1:]) if name[1:].isdigit() else 0, reverse=True)

    def pick(version: str | None) -> str:
        available = versions()
        if not available:
            raise HTTPException(503, "No knowledge base found. Run: python scripts/build_kb.py "
                                     "--manifest artifacts/gnn_embeddings_v3.json")
        if version is None:
            return available[0]
        if version not in available:
            raise HTTPException(404, f"Unknown data version {version}")
        return version

    @lru_cache(maxsize=8)
    def browser(version: str) -> Chatbot:
        return Chatbot.from_version(version, llm=_NoModel(), root=root)

    def chat_bot(session_id: str, version: str) -> Chatbot:
        key = f"{session_id}::{version}"
        if key not in sessions:
            sessions[key] = Chatbot.from_version(version, root=root, llm_factory=llm_factory)
        return sessions[key]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "versions": versions()}

    @app.get("/api/versions")
    def list_versions() -> dict[str, Any]:
        available = versions()
        return {"versions": available, "default": available[0] if available else None}

    @app.get("/api/overview")
    def overview(version: str | None = None) -> dict[str, Any]:
        version = pick(version)
        bot = browser(version)
        metrics, summary = bot.model_metrics(), bot.dataset_summary()
        head = views.headline(metrics)
        threshold = head.get("threshold", 0.5)
        return {"version": version, "headline": head, "threshold": threshold,
                "dataset_count": summary.get("count", len(bot.list_prs())),
                "warnings": metrics.get("warnings", []),
                "results": views.results_table(metrics),
                "scores": views.score_rows(bot.predictions(), "test", threshold),
                "splits": views.split_rows(summary),
                "purged": [pr.split("#")[-1] for pr in summary.get("purged", [])]}

    @app.get("/api/prs")
    def prs(version: str | None = None) -> dict[str, Any]:
        version = pick(version)
        bot = browser(version)
        threshold = views.headline(bot.model_metrics()).get("threshold", 0.5)
        ordered = sorted(bot.list_prs(), key=lambda meta: (not meta.get("explained"), meta["split"] != "test",
                                                          -meta["probability"]))
        return {"version": version, "threshold": threshold,
                "prs": [{**meta, "label_text": views.pr_label(meta, threshold)} for meta in ordered]}

    @app.get("/api/prs/detail")
    def pr_detail(sample_id: str, version: str | None = None) -> dict[str, Any]:
        version = pick(version)
        bot = browser(version)
        threshold = views.headline(bot.model_metrics()).get("threshold", 0.5)
        try:
            details = bot.pr_details(sample_id)
        except KeyError:
            raise HTTPException(404, f"Unknown PR {sample_id}")
        explanation = details.get("explanation")
        result: dict[str, Any] = {
            "sample_id": sample_id, "probability": details["probability"], "label": details["label"],
            "threshold": threshold, "correct": int(details["probability"] >= threshold) == details["label"],
            "card": details["card"], "explained": bool(explanation or details.get("attribution_v5")),
            "explanation": None,
            # v5 edge attributions are shown in the Attribution tab, not as the v4 layer A/B/C panels.
            "has_attribution_v5": bool(details.get("attribution_v5"))}
        if explanation:
            graph = explanation.get("graph")
            result["explanation"] = {
                "layer_a": views.layer_a_rows(explanation),
                "layer_b": views.layer_b_rows(explanation, TOP_HUNKS),
                "layer_c": ({"touched_total": graph["touched_files_total"],
                             "untouched_total": graph["untouched_files_total"],
                             "files": views.layer_c_rows(explanation, TOP_FILES)} if graph else None),
                "note": explanation.get("note", "")}
        return result

    @app.post("/api/live")
    async def live(request: LiveRequest) -> dict[str, Any]:
        version = pick(request.version)
        try:
            report, saved = await run_in_threadpool(
                analyze_live_pr, request.url.strip(), root,
                manifest_path=root / "artifacts" / f"gnn_embeddings_{version}.json",
                token=os.getenv("GITHUB_TOKEN"), max_hunks=request.max_hunks)
        except (LivePRError, OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc))
        explanation = report.get("xai")
        return {
            "sample_id": report["sample_id"], "url": report["url"], "title": report["title"],
            "risk_percent": report["risk_percent"], "classification": report["classification"],
            "gnn_probability": report["gnn_probability"], "threshold": report["threshold"],
            "warning": report["warning"], "layer_a": views.layer_a_rows(report),
            "hunks": views.layer_b_rows(explanation, TOP_HUNKS) if explanation else [],
            "saved_path": str(saved)}

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> dict[str, Any]:
        version = pick(request.version)
        try:
            bot = await run_in_threadpool(chat_bot, request.session_id, version)
            answer = await run_in_threadpool(bot.ask, request.question)
        except (LLMError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(422, str(exc))
        return {"text": answer.text, "sources": [card["id"] for card in answer.cards], "note": answer.note,
                "unsupported_numbers": list(answer.unsupported_numbers),
                "unknown_citations": list(answer.unknown_citations)}

    @app.post("/api/chat/reset")
    def chat_reset(request: ResetRequest) -> dict[str, str]:
        version = pick(request.version)
        bot = sessions.get(f"{request.session_id}::{version}")
        if bot:
            bot.reset()
        return {"status": "ok"}

    return app


app = create_app()
