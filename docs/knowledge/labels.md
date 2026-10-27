# Labels and data splits

## What label 1 and label 0 mean
Label 1 (risky) means: within six calendar months after the PR was merged, a reviewed
architectural refactor PR changed the same production Python files that this PR touched,
and the git history linking the two was verified. Label 0 (safe) means no such refactor
happened in that window and there were no unresolved overlapping PRs. A refactor that
later touches the same files does not prove the earlier PR caused architectural debt: the
label is an outcome proxy, not a causal claim.

## How a positive label is reviewed
A positive needs a reviewed architectural event: the refactor PR, the files it shares with
the sample PR, a written rationale and evidence links. PR titles or messages alone can never
make a PR positive or negative. Records with missing coverage or unresolved reviews get no
label and are never used as training negatives.

## How the data is split
In the current version (v4) whole repositories are kept apart, which is called a repository
holdout. Flask and Jinja are the training repositories, Click is the validation repository
used once to pick the decision threshold, and Werkzeug is the test repository that the
models never see while training. This stops a model from scoring well only because it
learned one project's habits. The earlier version (v3) split PRs by merge time instead and
purged (removed) PRs whose six-month window crossed a split cutoff. The dataset card lists
the PRs per split and per repository.

## Why the split sizes matter
The model learns only from the train split. The validation split is used once, to pick the
decision threshold (best F1). The test split is used once at the end to report results.
With very few PRs per split, one mistake changes the scores a lot, so results are reported
with bootstrap ranges.
