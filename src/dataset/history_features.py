"""v5.1 history features: how the code a PR touches was changing BEFORE the PR (no future data).

The label asks whether the touched modules gain coupling faster than their project over the
6 months after the merge. The same question asked about the 6 months before the merge is
legitimate input (it is history) and is the most direct clue a reviewer has. Features:

* Coupling momentum, from two snapshots of the main branch taken before the PR:
  ``recent`` = last commit before the merge month began, ``past`` = last commit 6 months
  before that. With the same definitions as the label (``future_coupling``):
  past_coupling_growth g, past_repository_trend Δ, past_excess_growth e = g − Δ,
  past_joined_cycle, and the share of touched modules that already existed 6 months ago.
* Coupling level just before the PR: mean/max total coupling C = Ca + Ce of the touched
  modules, the share of them in an import cycle, and the project's mean coupling and size.
* Change activity (git log, ``--first-parent`` on the branch before the PR): commits and
  distinct authors that touched the PR's files in the 182 days before the merge, and all
  commits to the project in that window (CodeScene-style hotspot and process metrics).

Both snapshots are older than the merge commit and the git queries stop at the commit before
the PR, so nothing here can see the outcome window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log1p
from pathlib import Path
from typing import Any, Callable

from src.dataset.future_coupling import future_coupling_label
from src.dataset.pr_history import _git, commit_at_or_before

HISTORY_FEATURE_NAMES: tuple[str, ...] = (
    "past_coupling_growth", "past_repository_trend", "past_excess_growth", "past_joined_cycle",
    "touched_existed_6_months_ago", "touched_mean_coupling", "touched_max_coupling", "touched_in_cycle_share",
    "repo_mean_coupling", "log_repo_modules", "log_file_commits_182d", "log_file_authors_182d",
    "log_repo_commits_182d",
)
HISTORY_SCHEMA = "history_v5/1"
WINDOW_MONTHS = 6
CHURN_DAYS = 182


def snapshot_moments(merged_at: str) -> tuple[datetime, datetime]:
    """(recent, past): the start of the merge month, and 6 calendar months before it (UTC)."""
    merged = datetime.fromisoformat(merged_at).astimezone(timezone.utc)
    recent = merged.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months = recent.year * 12 + recent.month - 1 - WINDOW_MONTHS
    return recent, recent.replace(year=months // 12, month=months % 12 + 1)


def history_features(repository: Path, record: dict[str, Any],
                     summary_of: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    """``summary_of(sha)`` returns ``coupling_summary`` of that commit (cached by the caller)."""
    before = record["before_commit_sha"]
    recent_moment, past_moment = snapshot_moments(record["merged_at"])
    recent_sha = commit_at_or_before(repository, recent_moment, ref=before)
    past_sha = commit_at_or_before(repository, past_moment, ref=before)
    touched = list(record["touched_modules"])
    values = dict.fromkeys(HISTORY_FEATURE_NAMES, 0.0)
    if recent_sha is not None:
        recent = summary_of(recent_sha)
        present = [name for name in touched if name in recent["modules"]]
        totals = [recent["modules"][name]["ca"] + recent["modules"][name]["ce"] for name in present]
        cyclic = set(recent["cyclic_modules"])
        values.update({
            "touched_mean_coupling": sum(totals) / len(totals) if totals else 0.0,
            "touched_max_coupling": float(max(totals, default=0)),
            "touched_in_cycle_share": sum(name in cyclic for name in present) / len(touched) if touched else 0.0,
            "repo_mean_coupling": float(recent["mean_coupling"]),
            "log_repo_modules": log1p(recent["module_count"]),
        })
        if past_sha is not None and past_sha != recent_sha:
            past = summary_of(past_sha)
            momentum = future_coupling_label(past, recent, touched, threshold=0.5)
            values["touched_existed_6_months_ago"] = (sum(name in past["modules"] for name in touched) / len(touched)
                                                      if touched else 0.0)
            if momentum["label"] is not None:
                values.update({"past_coupling_growth": momentum["coupling_growth"],
                               "past_repository_trend": momentum["repository_trend"],
                               "past_excess_growth": momentum["excess_growth"],
                               "past_joined_cycle": float(bool(momentum["joined_cycle"]))})
    since = (datetime.fromisoformat(record["merged_at"]) - timedelta(days=CHURN_DAYS)).isoformat()
    files = record["changed_python_files"]
    log = _git(repository, "log", "--first-parent", f"--since={since}", "--format=%H%x09%ae", before, "--", *files)
    rows = [line.split("\t") for line in log.splitlines() if "\t" in line]
    repo_commits = _git(repository, "rev-list", "--count", "--first-parent", f"--since={since}", before).strip()
    values.update({"log_file_commits_182d": log1p(len(rows)),
                   "log_file_authors_182d": log1p(len({author.lower() for _, author in rows})),
                   "log_repo_commits_182d": log1p(int(repo_commits or 0))})
    return {"schema": HISTORY_SCHEMA, "recent_commit_sha": recent_sha, "past_commit_sha": past_sha,
            "features": {name: float(values[name]) for name in HISTORY_FEATURE_NAMES}}
