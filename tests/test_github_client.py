from __future__ import annotations
import httpx
import pytest

from src.github.client import GitHubClient, GitHubGraphQLError, GitHubHTTPError
from tests.conftest import settings


def make_client(handler):
    return GitHubClient(settings(), token="test-token", http_client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)


def test_executes_graphql_and_returns_data():
    def handler(request):
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"data": {"viewer": {"login": "tester"}, "rateLimit": {"remaining": 4999}}})
    assert make_client(handler).execute("query X { viewer { login } }", {})["viewer"]["login"] == "tester"


def test_graphql_errors_are_raised():
    client = make_client(lambda request: httpx.Response(200, json={"errors": [{"message": "Bad credentials"}]}))
    with pytest.raises(GitHubGraphQLError, match="Bad credentials"):
        client.execute("query X { viewer { login } }", {})


def test_http_auth_error_is_not_retried():
    calls = 0
    def handler(request):
        nonlocal calls; calls += 1
        return httpx.Response(401, text="Unauthorized")
    with pytest.raises(GitHubHTTPError): make_client(handler).execute("q", {})
    assert calls == 1


def test_temporary_http_error_retries():
    calls = 0
    def handler(request):
        nonlocal calls; calls += 1
        return httpx.Response(503, text="temporary") if calls == 1 else httpx.Response(200, json={"data": {"rateLimit": {}}})
    make_client(handler).execute("q", {})
    assert calls == 2

