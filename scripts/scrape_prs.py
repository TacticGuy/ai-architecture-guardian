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
from src.dataset.future_refactor_labels import parse_timestamp


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument("--window-start", help="Inclusive merge-date start, timezone-aware ISO timestamp")
    parser.add_argument("--window-end", help="Inclusive merge-date end, timezone-aware ISO timestamp")
    parser.add_argument("--raw-output", type=Path, help="Raw JSONL; date-window mode defaults to raw_prs_v2.jsonl")
    parser.add_argument("--coverage", type=Path, default=ROOT / "data/raw/coverage_v2.json")
    parser.add_argument("--max-pages", type=int,
                        help="Optional pages per window run; capped collection remains incomplete")
    args = parser.parse_args(argv)
    for value in (args.max_prs, args.max_prs_per_repo, args.target_prs):
        if value is not None and value <= 0:
            parser.error("limits must be positive")
    if args.max_prs and args.all:
        parser.error("--max-prs is only valid with --repo")
    if args.max_prs_per_repo and args.repo:
        parser.error("--max-prs-per-repo is only valid with --all")
    if bool(args.window_start) != bool(args.window_end):
        parser.error("Supply both --window-start and --window-end")
    if args.window_start:
        start, end = parse_timestamp(args.window_start), parse_timestamp(args.window_end)
        if start is None or end is None or start >= end:
            parser.error("Window bounds must be ordered, timezone-aware ISO timestamps")
        if args.max_prs or args.max_prs_per_repo or args.target_prs:
            parser.error("PR count limits cannot certify a window; use --max-pages for a partial pilot")
    if args.max_pages is not None and (not args.window_start or args.max_pages <= 0):
        parser.error("--max-pages needs a date window and a positive value")
    return args


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
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
    window_mode = bool(args.window_start)
    checkpoint = None if window_mode else CheckpointStore(ROOT / "data/raw/scrape_checkpoint.json")
    if args.fresh and not window_mode:
        # Deliberately only reset cursors. Raw data is never deleted by this command.
        checkpoint.reset()
        logger.warning("--fresh reset the checkpoint only; existing raw JSONL was preserved and will be de-duplicated")
    successes: list[str] = []
    failures: list[str] = []
    incomplete: list[str] = []
    total_retrieved = 0
    try:
        with GitHubClient(settings, logger=logger) as client:
            raw_output = args.raw_output or ROOT / (
                "data/raw/raw_prs_v2.jsonl" if window_mode else "data/raw/raw_prs.jsonl"
            )
            scraper = PullRequestScraper(client, settings, str(raw_output), checkpoint, logger)
            for repo in repositories:
                remaining = None if args.target_prs is None else args.target_prs - total_retrieved
                if remaining is not None and remaining <= 0:
                    logger.info("Global target reached; stopping before next repository")
                    break
                configured_limit = args.max_prs if args.repo else args.max_prs_per_repo
                limit = min(configured_limit, remaining) if configured_limit and remaining else (configured_limit or remaining)
                try:
                    if window_mode:
                        result = scraper.scrape_window(
                            repo, args.window_start, args.window_end, args.coverage,
                            resume=not args.fresh, max_pages=args.max_pages,
                        )
                        print(f"{result['repo']}: window_prs={result['window_prs']} "
                              f"coverage_complete={result['completed']}")
                        if not result["completed"]:
                            incomplete.append(result["repo"])
                    else:
                        result = scraper.scrape_repository(repo, max_prs=limit, resume=not args.fresh)
                    total_retrieved += result["retrieved"]
                    successes.append(result["repo"])
                except (GitHubClientError, RuntimeError, ValueError, OSError) as exc:
                    failures.append(f"{repo['owner']}/{repo['name']}: {exc}")
                    logger.exception("Failed repository %s/%s", repo["owner"], repo["name"])
    except GitHubClientError as exc:
        logger.error("Could not start scraper: %s", exc)
        return 1
    print(f"Successful repositories: {len(successes)}")
    print(f"Failed repositories: {len(failures)}")
    if failures:
        print("Failures:\n" + "\n".join(failures))
    if incomplete:
        print("Incomplete windows: " + ", ".join(incomplete) + ". Re-run the same command to resume.")
    return 1 if failures else (2 if incomplete else 0)


if __name__ == "__main__":
    raise SystemExit(main())

