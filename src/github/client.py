"""Small retrying GitHub GraphQL HTTP client."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

from src.github.rate_limit import RateLimitManager


class GitHubClientError(RuntimeError):
    """Base GitHub API error."""


class GitHubHTTPError(GitHubClientError):
    """HTTP-level GitHub API error."""


class GitHubGraphQLError(GitHubClientError):
    """GraphQL-level GitHub API error."""


class GitHubClient:
    def __init__(self, settings: dict[str, Any], token: str | None = None,
                 http_client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
                 logger: logging.Logger | None = None) -> None:
        load_dotenv()
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise GitHubClientError("GITHUB_TOKEN is not set. Put it in .env or the environment.")
        self.settings = settings
        self.logger = logger or logging.getLogger("pr_dataset")
        self.client = http_client or httpx.Client(timeout=float(settings["request_timeout_seconds"]))
        self.owns_client = http_client is None
        self.sleep = sleep
        self.rate_limits = RateLimitManager(
            int(settings["rate_limit_warning_threshold"]), bool(settings["rate_limit_wait_enabled"]),
            int(settings["rate_limit_max_wait_seconds"]), sleep, self.logger)

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        retries = int(self.settings["max_retries"])
        base_delay = float(self.settings["retry_base_delay_seconds"])
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        for attempt in range(retries + 1):
            try:
                response = self.client.post(self.settings["graphql_endpoint"], json={"query": query, "variables": variables}, headers=headers)
                if response.status_code >= 400:
                    if response.status_code in {502, 503, 504} and attempt < retries:
                        self._retry_delay(attempt, response.status_code)
                        continue
                    raise GitHubHTTPError(f"GitHub HTTP {response.status_code}: {response.text[:500]}")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise GitHubClientError("GitHub returned malformed JSON") from exc
                if not isinstance(payload, dict):
                    raise GitHubClientError("GitHub returned a non-object GraphQL payload")
                if payload.get("errors"):
                    raise GitHubGraphQLError(self._format_graphql_errors(payload["errors"]))
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise GitHubClientError("GitHub response did not contain GraphQL data")
                self.rate_limits.handle(data.get("rateLimit"))
                return data
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < retries:
                    self._retry_delay(attempt, type(exc).__name__)
                    continue
                raise GitHubClientError(f"GitHub connection failed after retries: {exc}") from exc
        raise AssertionError("Unreachable")

    def _retry_delay(self, attempt: int, reason: object) -> None:
        delay = float(self.settings["retry_base_delay_seconds"]) * (2 ** attempt)
        self.logger.warning("Temporary GitHub failure (%s); retrying in %.1f seconds", reason, delay)
        self.sleep(delay)

    @staticmethod
    def _format_graphql_errors(errors: object) -> str:
        if not isinstance(errors, list):
            return "GitHub GraphQL returned an unknown error"
        messages = [str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors]
        return "GitHub GraphQL error: " + "; ".join(messages)

