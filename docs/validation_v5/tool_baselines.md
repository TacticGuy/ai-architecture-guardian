# Established tools as baselines: leakage check and rationale (v5, Mandatory 3)

radon, pylint and the hotspot write one row per PR to `data/tool_metrics_v5.jsonl`, with tool
versions and the run date in `data/tool_metrics_v5.meta.json`. SonarQube runs separately
(`scripts/sonar_v5.py`) and writes `data/sonar_v5.jsonl` and `data/sonar_v5.meta.json`.
Harsha's comparison script turns these rows into baseline models, trained on the training
repositories and scored on the held-out ones.

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
| SonarQube Community 26.10 | Code smells, cognitive complexity, technical debt in minutes (`sqale_index`); after + delta | The tool most companies run in CI to track technical debt. Run on all splits in batches (see below). Duplication is not reported. |

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

## How SonarQube was run

The plan was two scans per PR (before and after) on the test split only, because each scan
pays the scanner's start-up and the server's processing. Measured on real PRs, that was too
slow, so the scans were batched instead:

* **Batches of 250 PRs.** Each PR's touched files are written under their own folder
  (`<owner>__<repo>__<number>/<path>`), once at `before_commit_sha` and once at
  `merge_commit_sha`. Each side of a batch is one scan and one SonarQube project. Batches never
  mix splits. A first try with 500 PRs per batch stalled the scanner on memory, so batches
  are 250 PRs with a 3 GB scanner heap.
* **Per-PR numbers are sums.** Code smells, cognitive complexity and `sqale_index` are additive,
  so each PR's value is the sum of the file-level measures under its folder. Deltas are
  after − before. A side with no files (all files added or all deleted) counts as 0. A side
  whose files SonarQube returned nothing for is `null`, not 0.
* **Checked against single scans.** On two real PRs the batch numbers were identical to
  scanning each PR on its own.
* **Duplication is off** (`-Dsonar.cpd.exclusions=**/*`). In a batch it would compare code
  across 250 unrelated PRs, so `sonar.duplicated_lines_density` from the planned key set is
  not reported. The other six `sonar.*` keys are.
* **Stalls are split, not dropped.** A batch that fails or times out (30 minutes per scan) is
  split in half and retried, down to single PRs. This happened twice: a test batch with
  several very large textual files stalled and both halves then succeeded, and a train batch
  was split down to the one PR whose file crashes the analyzer (below).

Because batching made it fast enough (27 batches, about 5.6 hours of scanning), SonarQube
covers **all splits**, not only the test split. No subset was sampled.

## Coverage

* SonarQube: **6,140 of 6,141 PRs** have values (test 1,375 of 1,375, validation 1,190 of
  1,190, train 3,575 of 3,576), with no `null` rows. The one missing PR, `celery/kombu#1038`
  (train), changes one file, `kombu/transport/librabbitmq.py`, which crashes SonarQube's own
  Python analyzer (`java.lang.StackOverflowError`) even when scanned alone. It has no row, and
  is listed under `failed` in `data/sonar_v5.meta.json`.
* radon, pylint and hotspot: the full run used Harsha's parallel runner
  (`scripts/run_tool_metrics_v5.py`). Row counts and tool versions are in
  `data/tool_metrics_v5.meta.json`.
