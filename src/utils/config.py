"""Configuration loading and repository validation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPOSITORY_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_settings(path: str | Path = "config/settings.json") -> dict[str, Any]:
    settings = load_json(path)
    if not isinstance(settings, dict):
        raise ValueError("Settings must be a JSON object")
    return settings


def load_repositories(path: str | Path = "config/repositories.json") -> list[dict[str, Any]]:
    repositories = load_json(path)
    if not isinstance(repositories, list):
        raise ValueError("Repository configuration must be a JSON array")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(repositories):
        if not isinstance(entry, dict):
            raise ValueError(f"Repository entry {index} must be an object")
        owner, name = entry.get("owner"), entry.get("name")
        if not isinstance(owner, str) or not owner or not REPOSITORY_PART.fullmatch(owner):
            raise ValueError(f"Repository entry {index} has invalid owner")
        if not isinstance(name, str) or not name or not REPOSITORY_PART.fullmatch(name):
            raise ValueError(f"Repository entry {index} has invalid name")
        repo = f"{owner}/{name}"
        if repo.lower() in seen:
            raise ValueError(f"Duplicate repository: {repo}")
        seen.add(repo.lower())
        validated.append({"owner": owner, "name": name, "enabled": bool(entry.get("enabled", True))})
    return validated


def enabled_repositories(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [repository for repository in repositories if repository["enabled"]]

