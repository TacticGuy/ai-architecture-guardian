"""Groq chat client (OpenAI-compatible HTTP API), using httpx, which the project already needs.

The API key is read from the GROQ_API_KEY environment variable (put it in .env, which git
ignores). It is never printed or written anywhere.

Which models a key may use depends on the Groq account (see ``list_models``). If the main
model is unavailable or rate-limited, ``FallbackChat`` answers with the fallback model instead.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Protocol

import httpx

GROQ_BASE = "https://api.groq.com/openai/v1"
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    """The language model could not answer. ``kind`` is model, auth, rate, network or other."""

    def __init__(self, message: str, kind: str = "other") -> None:
        super().__init__(message)
        self.kind = kind


class ChatModel(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


def _key(api_key: str | None) -> str:
    key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise LLMError("GROQ_API_KEY is not set. Add a line GROQ_API_KEY=... to the .env file in the project "
                       "folder (create a key at console.groq.com).", "auth")
    return key


class GroqChat:
    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.0, max_tokens: int = 700,
                 options: dict[str, Any] | None = None, timeout: float = 60.0, retries: int = 2,
                 client: httpx.Client | None = None) -> None:
        key = _key(api_key)
        self.name, self.temperature, self.max_tokens, self.retries = model, temperature, max_tokens, retries
        self.options = dict(options or {})          # model-specific, e.g. {"reasoning_effort": "low"}
        self._headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self._client = client or httpx.Client(timeout=timeout)

    def complete(self, system: str, user: str) -> str:
        payload: dict[str, Any] = {"model": self.name, "temperature": self.temperature, "max_tokens": self.max_tokens,
                                   "messages": [{"role": "system", "content": system},
                                                {"role": "user", "content": user}], **self.options}
        for attempt in range(self.retries + 1):
            try:
                response = self._client.post(f"{GROQ_BASE}/chat/completions", headers=self._headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"Could not reach Groq ({type(exc).__name__}). Check your internet connection.",
                               "network") from exc
            if response.status_code == 200:
                try:
                    content = response.json()["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, ValueError, TypeError) as exc:
                    raise LLMError("Groq returned an answer in an unexpected format.") from exc
                content = _THINK.sub("", content).strip()      # some models put their reasoning in <think> tags
                if not content:
                    raise LLMError("Groq returned an empty answer (the model may have used all its tokens on "
                                   "reasoning). Try again or raise max_tokens in config/chatbot.json.")
                return content
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                wait = response.headers.get("retry-after")
                time.sleep(min(float(wait), 20.0) if wait and wait.replace(".", "", 1).isdigit() else 2 ** attempt)
                continue
            raise _explain(response)
        raise LLMError("Groq did not answer after several tries.")  # pragma: no cover - loop always returns/raises


class FallbackChat:
    """Use ``primary``; if its model is unavailable or rate-limited, answer with ``fallback``."""

    def __init__(self, primary: ChatModel, fallback: ChatModel | None) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.last_used = primary.name
        self.note = ""

    def complete(self, system: str, user: str) -> str:
        try:
            self.last_used, self.note = self.primary.name, ""
            return self.primary.complete(system, user)
        except LLMError as exc:
            if self.fallback is None or exc.kind not in ("model", "rate"):
                raise
            reason = "is not available to this key" if exc.kind == "model" else "is rate-limited right now"
            self.last_used = self.fallback.name
            self.note = f"{self.primary.name} {reason}; answered with {self.fallback.name}."
            return self.fallback.complete(system, user)


def list_models(api_key: str | None = None, client: httpx.Client | None = None) -> list[str]:
    """Model ids this Groq key may use."""
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {_key(api_key)}"})
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Groq ({type(exc).__name__}).", "network") from exc
    if response.status_code != 200:
        raise _explain(response)
    return sorted(model["id"] for model in response.json().get("data", []) if isinstance(model.get("id"), str))


def _explain(response: httpx.Response) -> LLMError:
    try:
        detail = response.json().get("error", {}).get("message", "")
    except ValueError:
        detail = ""
    if response.status_code == 401:
        return LLMError("Groq rejected the API key (401). Check GROQ_API_KEY in .env.", "auth")
    if response.status_code == 404 or ("model" in detail.lower() and response.status_code in (400, 403)):
        return LLMError(f"Groq model not available ({detail or response.status_code}). Run "
                        "'python scripts/chat.py --list-models' and set 'model' in config/chatbot.json.", "model")
    if response.status_code == 429:
        return LLMError("Groq rate limit reached (429). Wait a minute and ask again.", "rate")
    return LLMError(f"Groq error {response.status_code}: {detail or response.text[:200]}")
