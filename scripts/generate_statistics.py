"""Generate reproducibility metadata and a human-readable dataset report."""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.filtering.impact_filter import passes_impact_filter
from src.filtering.semantic_filter import semantic_filter
from src.storage.jsonl import iter_jsonl
from src.utils.config import enabled_repositories, load_repositories, load_settings
from src.utils.logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate dataset and filtering statistics.")
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/raw_prs.jsonl")
    parser.add_argument("--filtered", type=Path, default=ROOT / "data/filtered/filtered_prs.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "data/statistics/filtering_statistics.json")
    args = parser.parse_args()
    logger = configure_logging()
    if not args.raw.exists():
        print(f"Raw dataset does not exist: {args.raw}")
        return 1
    settings = load_settings(ROOT / "config/settings.json")
    repositories = load_repositories(ROOT / "config/repositories.json")
    per_repo: Counter[str] = Counter()
    changed: list[int] = []
    total = impact_passed = impact_rejected = semantic_passed = semantic_rejected = 0
    keyword_counts: Counter[str] = Counter()
    for pr in iter_jsonl(args.raw):
        total += 1
        per_repo[str(pr.get("repo", "unknown"))] += 1
        if isinstance(pr.get("changed_files"), int) and not isinstance(pr.get("changed_files"), bool):
            changed.append(pr["changed_files"])
        if not passes_impact_filter(pr, int(settings["impact_min_changed_files"])):
            impact_rejected += 1
            continue
        impact_passed += 1
        passed, matches = semantic_filter(pr, list(settings["semantic_keywords"]))
        if passed:
            semantic_passed += 1
            keyword_counts.update(matches)
        else:
            semantic_rejected += 1
    filtered_count = sum(1 for _ in iter_jsonl(args.filtered)) if args.filtered.exists() else 0
    checkpoint_path = ROOT / "data/raw/scrape_checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    completed = [repo for repo, state in checkpoint.items() if isinstance(state, dict) and state.get("completed")]
    configured = [f"{r['owner']}/{r['name']}" for r in repositories]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "scraper_version": settings["scraper_version"],
        "repository_list": repositories, "total_repositories": len(repositories), "enabled_repositories": len(enabled_repositories(repositories)),
        "repositories_successfully_scraped": len(completed), "repositories_failed_or_incomplete": sorted(set(configured) - set(completed)),
        "configuration": {"impact_min_changed_files": settings["impact_min_changed_files"], "semantic_keywords": settings["semantic_keywords"]},
        "total_raw_prs": total, "prs_per_repository": dict(sorted(per_repo.items())),
        "average_changed_files": statistics.mean(changed) if changed else None,
        "median_changed_files": statistics.median(changed) if changed else None,
        "impact_filter_passed": impact_passed, "impact_filter_rejected": impact_rejected,
        "semantic_filter_passed": semantic_passed, "semantic_filter_rejected": semantic_rejected,
        "final_accepted": filtered_count, "keyword_frequencies": dict(sorted(keyword_counts.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("=" * 50 + "\nDATASET STATISTICS\n")
    print(f"Repositories: {report['enabled_repositories']}")
    print(f"Raw merged PRs: {total}\n")
    print(f"Impact filter: Passed {impact_passed}; Rejected {impact_rejected}")
    print(f"Semantic filter: Passed {semantic_passed}; Rejected {semantic_rejected}")
    print(f"Final dataset: {filtered_count}\n\nKeyword matches:")
    for keyword, count in sorted(keyword_counts.items()):
        print(f"{keyword}: {count}")
    print("=" * 50)
    logger.info("Wrote statistics to %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

