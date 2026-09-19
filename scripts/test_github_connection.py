"""Check GitHub credentials and GraphQL reachability without scraping PRs."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.github.client import GitHubClient, GitHubClientError
from src.github.queries import VIEWER_QUERY
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def main() -> int:
    logger = configure_logging()
    settings = load_settings(ROOT / "config/settings.json")
    repositories = enabled_repositories(load_repositories(ROOT / "config/repositories.json"))
    if not repositories:
        print("No enabled repositories configured.")
        return 1
    repository = repositories[0]
    try:
        with GitHubClient(settings, logger=logger) as client:
            data = client.execute(VIEWER_QUERY, {"owner": repository["owner"], "name": repository["name"]})
        if not data.get("repository"):
            raise GitHubClientError("Configured test repository was not found or is inaccessible")
        print("GitHub API connection successful")
        print(f"Authenticated successfully as: {data['viewer']['login']}")
        print(f"Repository found: {data['repository']['nameWithOwner']}")
        print(f"Rate limit remaining: {data.get('rateLimit', {}).get('remaining', 'unknown')}")
        return 0
    except (GitHubClientError, KeyError) as exc:
        logger.error("GitHub connection test failed: %s", exc)
        print(f"GitHub connection test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

