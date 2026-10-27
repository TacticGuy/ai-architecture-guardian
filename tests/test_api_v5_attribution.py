"""/api/v5 attribution router, on the synthetic fixtures in tests/fixtures/attribution_v5/."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.v5_attribution import create_router  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "attribution_v5"


@pytest.fixture
def root(tmp_path):
    xai = tmp_path / "data/xai/v5"
    xai.mkdir(parents=True)
    for path in FIXTURES.glob("*.json"):
        shutil.copy(path, xai / path.name)
    explanations = tmp_path / "data/rag_v5/explanations"
    explanations.mkdir(parents=True)
    shutil.copy(FIXTURES / "explanations/pallets__flask__5123.json", explanations)
    (xai / "o__bad__1.json").write_text(json.dumps({"schema": "attribution_v4/1", "sample_id": "o/bad#1"}))
    (xai / "o__broken__2.json").write_text("{not json")
    (tmp_path / "secret.json").write_text(json.dumps({"schema": "attribution_v5/1", "sample_id": "leak"}))
    return tmp_path


@pytest.fixture
def client(root):
    app = FastAPI()
    app.include_router(create_router(root))
    return TestClient(app)


def test_list_skips_bad_files_and_sorts_by_risk(client, caplog):
    with caplog.at_level("WARNING"):
        rows = client.get("/api/v5/attributions").json()
    assert [row["sample_id"] for row in rows] == ["pallets/flask#5123", "psf/requests#7010", "pallets/click#2934"]
    assert rows[0] == {"sample_id": "pallets/flask#5123", "repo": "pallets/flask",
                       "title": "Move CLI loading into app factory", "risk_score": 0.81, "threshold": 0.47,
                       "predicted_degrading": True, "label": 1, "split": "test", "has_explanation": True}
    assert rows[1]["label"] is None and not rows[1]["has_explanation"]
    assert "o__bad__1.json" in caplog.text and "o__broken__2.json" in caplog.text


@pytest.mark.parametrize("params, expected", [
    ({"split": "test"}, ["pallets/flask#5123", "pallets/click#2934"]),
    ({"degrading": "true"}, ["pallets/flask#5123", "psf/requests#7010"]),
    ({"degrading": "false"}, ["pallets/click#2934"]),
    ({"q": "FLASK"}, ["pallets/flask#5123"]),
    ({"q": "proxy auth"}, ["psf/requests#7010"]),
    ({"split": "test", "degrading": "true", "q": "flask"}, ["pallets/flask#5123"]),
])
def test_list_filters(client, params, expected):
    assert [row["sample_id"] for row in client.get("/api/v5/attributions", params=params).json()] == expected


def test_detail_with_and_without_explanation(client):
    detail = client.get("/api/v5/attributions/pallets/flask/5123").json()
    assert detail["schema"] == "attribution_v5/1" and len(detail["top_edges"]) == 7
    assert detail["explanation"]["verdict"] == "degrading" and detail["explanation"]["principles"] == ["ADP", "DIP"]
    assert client.get("/api/v5/attributions/psf/requests/7010").json()["explanation"] is None


def test_missing_and_invalid_files_are_404(client):
    assert client.get("/api/v5/attributions/pallets/flask/1").status_code == 404
    assert client.get("/api/v5/attributions/o/bad/1").status_code == 404  # wrong schema is never served


@pytest.mark.parametrize("path", [
    "/api/v5/attributions/../../secret/1",
    "/api/v5/attributions/..%2F..%2Fsecret/x/1",
    "/api/v5/attributions/%2E%2E/secret/1",
    "/api/v5/attributions/../secret/1",
    "/api/v5/attributions/a%5Cb/c/1",
    "/api/v5/attributions/o/r/0",
    "/api/v5/attributions/o/r/-1",
    "/api/v5/attributions/o/r/1.json",
])
def test_path_traversal_is_rejected(client, path):
    response = client.get(path)
    assert response.status_code in (400, 404, 422)
    assert "leak" not in response.text


def test_empty_data_folder_lists_nothing(tmp_path):
    app = FastAPI()
    app.include_router(create_router(tmp_path))
    assert TestClient(app).get("/api/v5/attributions").json() == []


def test_main_app_includes_the_router(root):
    from api.main import create_app
    assert TestClient(create_app(root)).get("/api/v5/attributions").status_code == 200
