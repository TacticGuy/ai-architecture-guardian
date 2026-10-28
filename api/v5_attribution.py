"""v5 attribution files (data/xai/v5/) and their RAG explanations (data/rag_v5/explanations/).

    GET /api/v5/attributions                          list, optional ?split=&degrading=&q=
    GET /api/v5/attributions/{owner}/{repo}/{number}  one attribution JSON + "explanation" (or null)

Files are named <owner>__<repo>__<number>.json. A file is served only if it is valid JSON with
``schema == "attribution_v5/1"``; anything else is skipped and logged. Paths are built only from
an owner/repo matching ``^[A-Za-z0-9_.-]+$`` and an integer number, never from raw input.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

SCHEMA = "attribution_v5/1"
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
log = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("Skipping unreadable file %s: %s", path.name, exc)
        return None
    if not isinstance(data, dict):
        log.warning("Skipping %s: not a JSON object", path.name)
        return None
    return data


def _read_attribution(path: Path) -> dict[str, Any] | None:
    data = _read_json(path)
    if data is not None and data.get("schema") != SCHEMA:
        log.warning("Skipping %s: schema is %r, expected %r", path.name, data.get("schema"), SCHEMA)
        return None
    return data


def _valid_name(value: str) -> bool:
    return bool(_NAME.fullmatch(value)) and value.strip(".") != ""


def create_router(root: Path, xai_dir: Path | None = None, explanations_dir: Path | None = None) -> APIRouter:
    xai_dir = Path(xai_dir or root / "data/xai/v5")
    explanations_dir = Path(explanations_dir or root / "data/rag_v5/explanations")
    router = APIRouter(prefix="/api/v5", tags=["v5 attribution"])

    @router.get("/attributions")
    def list_attributions(split: str | None = None, degrading: bool | None = None,
                          q: str | None = Query(default=None, max_length=200)) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(xai_dir.glob("*.json")) if xai_dir.is_dir() else []:
            data = _read_attribution(path)
            if data is None:
                continue
            if split and data.get("split") != split:
                continue
            if degrading is not None and bool(data.get("predicted_degrading")) != degrading:
                continue
            if q and q.lower() not in " ".join(str(data.get(k, "")) for k in ("sample_id", "repo", "title")).lower():
                continue
            rows.append({"sample_id": data.get("sample_id"), "repo": data.get("repo"), "title": data.get("title"),
                         "risk_score": data.get("risk_score"), "threshold": data.get("threshold"),
                         "predicted_degrading": data.get("predicted_degrading"), "label": data.get("label"),
                         "split": data.get("split"), "has_explanation": (explanations_dir / path.name).is_file()})
        return sorted(rows, key=lambda row: -(row["risk_score"] or 0))

    @router.get("/attributions/{owner}/{repo}/{number}")
    def get_attribution(owner: str, repo: str, number: int) -> dict[str, Any]:
        if not (_valid_name(owner) and _valid_name(repo)) or number < 1:
            raise HTTPException(400, "Invalid repository or PR number")
        name = f"{owner}__{repo}__{number}.json"
        path = xai_dir / name
        if not path.is_file():
            raise HTTPException(404, f"No attribution for {owner}/{repo}#{number}")
        data = _read_attribution(path)
        if data is None:
            raise HTTPException(404, f"Attribution for {owner}/{repo}#{number} is not a valid {SCHEMA} file")
        explanation_path = explanations_dir / name
        return {**data, "explanation": _read_json(explanation_path) if explanation_path.is_file() else None}

    return router
