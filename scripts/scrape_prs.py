"""CLI for resumable GitHub GraphQL PR metadata collection."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.github.client import GitHubClient, GitHubClientError
from src.scraper.checkpoint import CheckpointStore
from src.scraper.pr_scraper import PullRequestScraper
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape merged pull-request metadata using GitHub GraphQL.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="One configured repository, e.g. django/django")
    group.add_argument("--all", action="store_true", help="All enabled repositories")
    parser.add_argument("--max-prs", type=int, help="Maximum PRs for --repo (page requests are sized to this exact cap)")
    parser.add_argument("--max-prs-per-repo", type=int, help="Per-repository maximum for --all")
    parser.add_argument("--target-prs", type=int, help="Global maximum across this invocation; stops at page boundaries")
    parser.add_argument("--resume", action="store_true", help="Resume saved cursors and skip completed repositories")
    parser.add_argument("--fresh", action="store_true", help="Start traversal from initial cursors; preserves existing raw JSONL and skips its duplicates")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    for value in (args.max_prs, args.max_prs_per_repo, args.target_prs):
        if value is not None and value <= 0:
            parser.error("limits must be positive")
    if args.max_prs and args.all:
        parser.error("--max-prs is only valid with --repo")
    if args.max_prs_per_repo and args.repo:
        parser.error("--max-prs-per-repo is only valid with --all")
    return args


def main() -> int:
    args = arguments()
    logger = configure_logging(ROOT / "logs/pipeline.log", args.verbose)
    settings = load_settings(ROOT / "config/settings.json")
    repositories = enabled_repositories(load_repositories(ROOT / "config/repositories.json"))
    print(f"Repositories configured: {len(load_repositories(ROOT / 'config/repositories.json'))}")
    print(f"Repositories enabled: {len(repositories)}")
    print(f"Repositories disabled: {len(load_repositories(ROOT / 'config/repositories.json')) - len(repositories)}")
    if args.repo:
        repositories = [r for r in repositories if f"{r['owner']}/{r['name']}".lower() == args.repo.lower()]
        if not repositories:
            logger.error("%s is not an enabled configured repository", args.repo)
            return 2
    checkpoint = CheckpointStore(ROOT / "data/raw/scrape_checkpoint.json")
    if args.fresh:
        # Deliberately only reset cursors. Raw data is never deleted by this command.
        checkpoint.reset()
        logger.warning("--fresh reset the checkpoint only; existing raw JSONL was preserved and will be de-duplicated")
    successes: list[str] = []
    failures: list[str] = []
    total_retrieved = 0
    try:
        with GitHubClient(settings, logger=logger) as client:
            scraper = PullRequestScraper(client, settings, str(ROOT / "data/raw/raw_prs.jsonl"), checkpoint, logger)
            for repo in repositories:
                remaining = None if args.target_prs is None else args.target_prs - total_retrieved
                if remaining is not None and remaining <= 0:
                    logger.info("Global target reached; stopping before next repository")
                    break
                configured_limit = args.max_prs if args.repo else args.max_prs_per_repo
                limit = min(configured_limit, remaining) if configured_limit and remaining else (configured_limit or remaining)
                try:
                    result = scraper.scrape_repository(repo, max_prs=limit, resume=not args.fresh)
                    total_retrieved += result["retrieved"]
                    successes.append(result["repo"])
                except (GitHubClientError, RuntimeError) as exc:
                    failures.append(f"{repo['owner']}/{repo['name']}: {exc}")
                    logger.exception("Failed repository %s/%s", repo["owner"], repo["name"])
    except GitHubClientError as exc:
        logger.error("Could not start scraper: %s", exc)
        return 1
    print(f"Successful repositories: {len(successes)}")
    print(f"Failed repositories: {len(failures)}")
    if failures:
        print("Failures:\n" + "\n".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

