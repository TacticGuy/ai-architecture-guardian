"""Clone configured repositories locally for static analysis (point 1)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.repository.clone import RepositoryCloneError, RepositoryCloner, repository_id, write_clone_manifest
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Clone enabled GitHub repositories for points 1–4 static analysis.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--repo", help="One configured repository, for example django/django")
    selection.add_argument("--all", action="store_true", help="All enabled configured repositories")
    parser.add_argument("--update", action="store_true", help="Explicitly fetch and fast-forward existing clones")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logger = configure_logging(ROOT / "logs/pipeline.log", args.verbose)
    settings = load_settings(ROOT / "config/settings.json")
    repositories = enabled_repositories(load_repositories(ROOT / "config/repositories.json"))
    if args.repo:
        repositories = [repo for repo in repositories if repository_id(repo).lower() == args.repo.lower()]
        if not repositories:
            parser.error(f"{args.repo!r} is not an enabled configured repository")
    storage = ROOT / settings["repository_storage_directory"]
    manifest_path = storage / "clone_manifest.json"
    old_manifest = _read_manifest(manifest_path)
    records = {record.get("repo"): record for record in old_manifest if isinstance(record, dict) and record.get("repo")}
    cloner = RepositoryCloner(storage, int(settings["clone_timeout_seconds"]), logger)
    failures: list[str] = []
    for repository in repositories:
        try:
            record = cloner.clone_or_update(repository, update=args.update)
            records[record["repo"]] = record
            print(f"{record['action'].capitalize()}: {record['repo']} @ {record['head_commit']}")
        except RepositoryCloneError as exc:
            failures.append(f"{repository_id(repository)}: {exc}")
            logger.error("Clone failed for %s: %s", repository_id(repository), exc)
    write_clone_manifest(manifest_path, [records[key] for key in sorted(records)])
    print(f"Successful repositories: {len(repositories) - len(failures)}")
    print(f"Failed repositories: {len(failures)}")
    if failures:
        print("Failures:\n" + "\n".join(failures))
    return 1 if failures else 0


def _read_manifest(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


if __name__ == "__main__":
    raise SystemExit(main())

