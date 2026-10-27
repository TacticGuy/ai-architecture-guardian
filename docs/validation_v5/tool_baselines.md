# Established tools as baselines: leakage check and rationale (v5, Mandatory 3)

`scripts/tool_metrics_v5.py` writes one row per PR to `data/tool_metrics_v5.jsonl`. Tool
versions, the run date and the SonarQube subset are recorded in
`data/tool_metrics_v5.meta.json`. Harsha's comparison script turns these rows into baseline
models, trained on the training repositories and scored on the held-out ones.

## Only information from before the merge

* **Every file is read with `git show <sha>:<path>`** at `before_commit_sha` (the base branch
  just before the PR) and at `merge_commit_sha` (the PR applied). Both exist at merge time;
  nothing later is opened.
* **The hotspot window** counts commits that touched a file, walking back from
  `before_commit_sha` (`git rev-list <before> --since=<merged_at − 182 days> -- <path>`). The
  walk starts at the pre-merge commit, so neither the PR itself nor anything after the merge
  can be counted. A test with a later commit in a temporary repository checks this.
* **No tool sees the label.** The label is coupling growth in the 6 months *after* the merge,
  and no tool reads anything from that period.
* **These are pre-merge features**, the same information a reviewer has at review time. A
  delta (after − before) describes the PR's own change, not its future.

## Why each tool is a fair "industry" baseline

| Tool | Measures | Why it is a fair baseline |
|---|---|---|
| radon 6.0.1 | Cyclomatic complexity, maintainability index, SLOC; after + delta | The standard Python implementation of the McCabe and maintainability-index metrics that classic defect- and debt-prediction work uses. |
| pylint 4.1.3 | Score, messages per category, R09xx design checks (too many arguments, branches, ...), refactor messages per KLOC | The most widely used Python linter. Its design checks are the closest thing in a linter to "this code is getting hard to change". |
| CodeScene-style hotspot | Change frequency of the touched files in the 182 days before the merge × their complexity | CodeScene's published hotspot method (Tornhill, *Your Code as a Crime Scene*), rebuilt with `git log`: files that change often and are complex predict trouble. This is our implementation, **not CodeScene**. |
| SonarQube Community | Code smells, cognitive complexity, technical debt in minutes (`sqale_index`), duplication; after + delta | The tool most companies run in CI to track technical debt. Test split only, because each PR takes two scans. |

## What these tools cannot see

All four work **per file**: they score the files a PR touches, one at a time. None of them
represents *which other modules* a file depends on, or who depends on it. A PR can therefore
leave every touched file's complexity, smells and lint score unchanged and still add a new
import between two layers, close an import cycle, or make a core module depend on a
peripheral one. That is exactly the cross-module coupling growth our label measures. The
hotspot comes closest, since it uses change history, but it still ranks single files, not the
links between them. This gap is the motivation for a graph model. If these baselines do as
well as the GNN, the graph is not adding information, and the comparison is designed to show
that honestly.

## CodeScene itself

We did not collect CodeScene's own numbers. CodeScene's pricing page says it is "free for
open-source projects" (a community edition), but it is a hosted service that needs a
CodeScene account linked to the repositories it analyses. Its analysis describes a
repository's *current* state, not the 6,141 historical before/after snapshots we need, and we
could not confirm a free-tier export of per-file Code Health scores. Collecting a qualitative
Code Health comparison for 2–3 repositories would need someone to sign up with their own
account. We did not fake those numbers. Instead, the hotspot baseline re-implements
CodeScene's published method on exactly our snapshots.

## Coverage (filled in after the full run)

* Rows in `tool_metrics_v5.jsonl`, and how many have radon, pylint and hotspot: see the meta file.
* SonarQube: test-split PRs scanned, and the seed if a subset was used: see the meta file.
