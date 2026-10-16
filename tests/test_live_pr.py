from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.live_pr import LivePRError, PRReference, fetch_pr, parse_pr_url


def test_parse_canonical_github_pr_url():
    reference = parse_pr_url("https://github.com/pallets/werkzeug/pull/123/")
    assert reference == PRReference("pallets", "werkzeug", 123)
    assert reference.sample_id == "pallets/werkzeug#123"


@pytest.mark.parametrize("url", [
    "https://example.com/a/b/pull/1", "https://github.com/a/b/issues/1",
    "https://github.com/a/b/pull/0", "https://github.com/a/b/pull/1/files",
])
def test_rejects_noncanonical_or_unsafe_urls(url):
    with pytest.raises(LivePRError):
        parse_pr_url(url)


def test_fetch_pr_extracts_exact_revisions_and_auth_header():
    payload = {"html_url": "https://github.com/o/r/pull/7", "title": "Small change", "state": "open",
               "draft": False, "base": {"sha": "A" * 40, "repo": {"clone_url": "https://github.com/o/r.git"}},
               "head": {"sha": "B" * 40}}
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps(payload).encode()

    def opener(request, timeout):
        seen["request"], seen["timeout"] = request, timeout
        return Response()

    result = fetch_pr(PRReference("o", "r", 7), "secret", opener)
    assert result["sample_id"] == "o/r#7"
    assert result["base_sha"] == "a" * 40
    assert result["head_sha"] == "b" * 40
    assert seen["request"].get_header("Authorization") == "Bearer secret"
    assert seen["timeout"] == 30
