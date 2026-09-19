"""Append-safe and streaming JSONL operations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


class JSONLFormatError(ValueError):
    """A JSONL line cannot be decoded."""


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JSONLFormatError(f"{source}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise JSONLFormatError(f"{source}:{line_number}: expected JSON object")
            yield record


class JSONLAppender:
    """Append records once, retaining only compact PR identifiers in memory."""
    def __init__(self, path: str | Path, id_field: str = "pr_id") -> None:
        self.path = Path(path)
        self.id_field = id_field
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.existing_ids = {str(record[id_field]) for record in iter_jsonl(self.path) if record.get(id_field) is not None}

    def append(self, record: dict[str, Any]) -> bool:
        identifier = record.get(self.id_field)
        if not identifier:
            raise ValueError(f"Record lacks required {self.id_field}")
        identifier = str(identifier)
        if identifier in self.existing_ids:
            return False
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
            handle.flush()
        self.existing_ids.add(identifier)
        return True


def write_jsonl_atomic(path: str | Path, records: Iterator[dict[str, Any]]) -> int:
    """Replace a derived JSONL file only after a complete successful write."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    temporary.replace(destination)
    return count

