"""FastAPI backend, run against the same small test project as the view-helper tests (no Groq calls)."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_chatbot import ScriptedModel  # noqa: E402
from tests.test_views import project_root  # noqa: E402


@pytest.fixture
def client(tmp_path):
    factory = lambda config: ScriptedModel("PR o/r#30 scored 0.765 [pr:o/r#30].")  # noqa: E731
    return TestClient(create_app(project_root(tmp_path), llm_factory=factory))


def test_overview_matches_the_view_tables(client):
    assert client.get("/api/versions").json() == {"versions": ["v7"], "default": "v7"}
    data = client.get("/api/overview").json()
    assert data["dataset_count"] == 7 and data["headline"]["fusion_ap"] == 0.577
    assert [row["Model"] for row in data["results"]][-1] == "Fusion"
    assert [row["PR"] for row in data["scores"]] == ["#30", "#32", "#31"]


def test_pr_list_and_explanation_layers(client):
    prs = client.get("/api/prs").json()["prs"]
    assert prs[0]["label_text"].startswith("#30 · test · risky") and prs[0]["explained"]
    detail = client.get("/api/prs/detail", params={"sample_id": "o/r#30"}).json()
    assert detail["correct"] and detail["explanation"]["layer_b"][0]["Lines"] == "207-218"
    assert [row["Touched by PR"] for row in detail["explanation"]["layer_c"]["files"]] == ["touched", "not touched"]
    unexplained = client.get("/api/prs/detail", params={"sample_id": "o/r#32"}).json()
    assert unexplained["explanation"] is None and not unexplained["correct"]
    assert client.get("/api/prs/detail", params={"sample_id": "o/r#999"}).status_code == 404


def test_v5_attribution_counts_as_explained_but_not_as_v4_layers(client, tmp_path):
    """A v5 edge-attribution file is explained (shown in the Attribution tab), never fed to layer A/B/C."""
    import json
    folder = tmp_path / "root/data/xai/v7"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "o__r__32.json").write_text(json.dumps({"schema": "attribution_v5/1", "sample_id": "o/r#32"}),
                                         encoding="utf-8")
    detail = client.get("/api/prs/detail", params={"sample_id": "o/r#32"}).json()
    assert detail["explained"] and detail["has_attribution_v5"] and detail["explanation"] is None
    v4 = client.get("/api/prs/detail", params={"sample_id": "o/r#30"}).json()
    assert v4["explanation"] is not None and not v4["has_attribution_v5"]


def test_chat_answers_with_sources_and_rejects_empty(client):
    answer = client.post("/api/chat", json={"question": "Why is PR #30 risky?", "session_id": "s1"}).json()
    assert "0.765" in answer["text"] and "pr:o/r#30" in answer["sources"]
    assert client.post("/api/chat/reset", json={"session_id": "s1"}).json() == {"status": "ok"}
    assert client.post("/api/chat", json={"question": ""}).status_code == 422


def test_live_rejects_a_bad_url_and_unknown_version(client):
    response = client.post("/api/live", json={"url": "not a url"})
    assert response.status_code == 422 and "github.com" in response.json()["detail"]
    assert client.get("/api/overview", params={"version": "v99"}).status_code == 404


def test_missing_knowledge_base_explains_how_to_build_it(tmp_path):
    response = TestClient(create_app(tmp_path)).get("/api/overview")
    assert response.status_code == 503 and "build_kb.py" in response.json()["detail"]
