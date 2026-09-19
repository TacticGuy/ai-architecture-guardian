"""Atomic checkpoint persistence for resumable repository pagination."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
                raise ValueError("checkpoint root must map repositories to objects")
            return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            self.path.replace(backup)
            raise ValueError(f"Corrupt checkpoint moved to {backup}: {exc}") from exc

    def get(self, repository: str) -> dict[str, Any]:
        return dict(self.data.get(repository, {"cursor": None, "completed": False}))

    def update(self, repository: str, cursor: str | None, completed: bool) -> None:
        self.data[repository] = {"cursor": cursor, "completed": completed}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(self.path)

    def reset(self) -> None:
        self.data = {}
        self.path.unlink(missing_ok=True)

