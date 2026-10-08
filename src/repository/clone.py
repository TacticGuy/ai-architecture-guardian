"""Reproducible, Git-CLI based repository cloning and clone manifests."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RepositoryCloneError(RuntimeError):
    """Git is unavailable or a clone/update operation failed."""


def repository_id(repository: dict[str, Any]) -> str:
    return f"{repository['owner']}/{repository['name']}"


def clone_destination(storage_directory: str | Path, repository: dict[str, Any]) -> Path:
    """Return a validated target below the designated repository storage directory."""
    root = Path(storage_directory).resolve()
    destination = (root / repository["owner"] / repository["name"]).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise RepositoryCloneError(f"Unsafe clone destination: {destination}") from exc
    return destination


class RepositoryCloner:
    def __init__(self, storage_directory: str | Path, timeout_seconds: int,
                 logger: logging.Logger | None = None) -> None:
        self.storage_directory = Path(storage_directory)
        self.timeout_seconds = timeout_seconds
        self.logger = logger or logging.getLogger("pr_dataset")

    def clone_or_update(self, repository: dict[str, Any], update: bool = False) -> dict[str, Any]:
        """Clone once; update an existing working copy only when explicitly requested."""
        repo_name = repository_id(repository)
        destination = clone_destination(self.storage_directory, repository)
        remote = f"https://github.com/{repo_name}.git"
        if destination.exists():
            if not (destination / ".git").is_dir():
                raise RepositoryCloneError(f"Destination exists but is not a Git repository: {destination}")
            action = "existing"
            if update:
                self.logger.info("Updating %s", repo_name)
                self._run(["git", "-C", str(destination), "fetch", "--prune", "origin"])
                self._run(["git", "-C", str(destination), "pull", "--ff-only"])
                action = "updated"
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.logger.info("Cloning %s into %s", repo_name, destination)
            self._run(["git", "clone", "--filter=blob:none", remote, str(destination)])
            action = "cloned"
        commit = self._run(["git", "-C", str(destination), "rev-parse", "HEAD"]).stdout.strip()
        branch = self._run(["git", "-C", str(destination), "branch", "--show-current"]).stdout.strip() or None
        return {
            "repo": repo_name,
            "path": str(destination),
            "remote_url": remote,
            "head_commit": commit,
            "branch": branch,
            "action": action,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(command, check=True, capture_output=True, text=True,
                                  timeout=self.timeout_seconds, encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise RepositoryCloneError("Git is not installed or is not available on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise RepositoryCloneError(f"Git command timed out after {self.timeout_seconds}s: {' '.join(command[:2])}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "Git command failed").strip()
            raise RepositoryCloneError(f"Git command failed: {stderr[:1000]}") from exc


def write_clone_manifest(path: str | Path, entries: list[dict[str, Any]]) -> None:
    """Write all clone provenance atomically after a command completes."""
    manifest = Path(path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_suffix(manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest)
