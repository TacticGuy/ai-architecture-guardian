"""Create AST, dependency graph, and node feature artifacts (points 2–4)."""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.pipeline import analyse_repository
from src.repository.clone import clone_destination, repository_id
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Statically analyse cloned Python repositories through flow-graph point 4.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--repo", help="One configured, already-cloned repository, e.g. django/django")
    selection.add_argument("--all", action="store_true", help="All enabled, already-cloned repositories")
    selection.add_argument("--path", type=Path, help="One explicit local repository path")
    parser.add_argument("--include-tests", action="store_true", help="Include test directories in static analysis")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logger = configure_logging(ROOT / "logs/pipeline.log", args.verbose)
    settings = load_settings(ROOT / "config/settings.json")
    analysis_settings = copy.deepcopy(settings["static_analysis"])
    if args.include_tests:
        analysis_settings["include_tests"] = True
    targets: list[tuple[str, Path]] = []
    if args.path:
        targets.append((args.path.resolve().name, args.path.resolve()))
    else:
        repositories = enabled_repositories(load_repositories(ROOT / "config/repositories.json"))
        if args.repo:
            repositories = [repo for repo in repositories if repository_id(repo).lower() == args.repo.lower()]
            if not repositories:
                parser.error(f"{args.repo!r} is not an enabled configured repository")
        storage = ROOT / settings["repository_storage_directory"]
        targets = [(repository_id(repo), clone_destination(storage, repo)) for repo in repositories]
    failures: list[str] = []
    for name, repository_path in targets:
        if not repository_path.is_dir():
            failures.append(f"{name}: clone not found at {repository_path}; run clone_repositories.py first")
            continue
        output = ROOT / settings["analysis_output_directory"] / name.replace("/", "__")
        try:
            result = analyse_repository(repository_path, output, analysis_settings)
            summary = result["graph"]["summary"]
            print(f"Analysed {name}: {summary['parsed_file_count']} files, {summary['node_count']} nodes, {summary['edge_count']} edges")
            logger.info("Analysed %s into %s", name, output)
        except (OSError, ValueError) as exc:
            failures.append(f"{name}: {exc}")
            logger.exception("Analysis failed for %s", name)
    if failures:
        print("Failures:\n" + "\n".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
