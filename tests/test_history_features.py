"""v5.1 history features: pre-merge coupling momentum and change activity, never future data."""
from __future__ import annotations

from math import log1p
import subprocess

import pytest

from src.dataset.history_features import HISTORY_FEATURE_NAMES, history_features, snapshot_moments
from src.dataset.pr_history import merged_prs_from_history
from tests.test_future_coupling import SETTINGS, commit, git, history_repo  # noqa: F401  (fixture)


def test_snapshot_moments_are_the_merge_month_start_and_six_months_earlier():
    recent, past = snapshot_moments("2021-03-17T10:00:00+05:30")
    assert recent.isoformat() == "2021-03-01T00:00:00+00:00"
    assert past.isoformat() == "2020-09-01T00:00:00+00:00"


def test_history_uses_only_commits_before_the_pr(history_repo, tmp_path):  # noqa: F811
    from src.dataset.coupling_builder import Snapshotter, analyse
    from src.dataset.future_coupling import coupling_summary
    commit(history_repo, {"pkg/e.py": "import pkg.b\n"}, "Use b in e (#4)", "2021-11-15T10:00:00+00:00")
    prs = {pr.number: pr for pr in merged_prs_from_history(history_repo)}
    snapshots = Snapshotter(history_repo, tmp_path / "wt")
    asked = []

    def summary_of(sha):
        asked.append(sha)
        return coupling_summary(analyse(snapshots.checkout(sha), SETTINGS)[0])

    pr = prs[4]
    record = {"before_commit_sha": pr.before_sha, "merged_at": pr.merged_at, "touched_modules": ["pkg.b"],
              "changed_python_files": ["pkg/e.py", "pkg/b.py"]}
    payload = history_features(history_repo, record, summary_of)
    features = payload["features"]
    assert list(features) == list(HISTORY_FEATURE_NAMES)
    # Both snapshots are ancestors of the commit before the PR: no information from the PR or later.
    for sha in asked:
        assert subprocess.run(["git", "-C", str(history_repo), "merge-base", "--is-ancestor", sha, pr.before_sha]).returncode == 0
    # recent = last commit before 2021-11-01 ("Later work", 2021-09-20); past = before 2021-05-01 (#2, 2021-03-10).
    # pkg.b then: C = Ca + Ce. At #2: a->b, so C(b)=1. At "Later work": a->b, b->a, c->a, c->b, d->a: C(b)=3.
    assert features["touched_mean_coupling"] == 3.0 and features["touched_existed_6_months_ago"] == 1.0
    assert features["past_coupling_growth"] == pytest.approx(2.0)
    assert features["past_joined_cycle"] == 1.0                     # b joined the a<->b cycle in that window
    # Commits on pkg/b.py in the 182 days before 2021-11-15: #3 (2021-06-10) only.
    assert features["log_file_commits_182d"] == pytest.approx(log1p(1))
