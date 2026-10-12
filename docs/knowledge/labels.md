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

## Time-based split and purging
PRs are split by time, not at random, because the tool must predict future PRs from past
ones. Train PRs have their whole six-month outcome window before the first cutoff;
validation PRs start after it and finish before the second cutoff; test PRs start after
the second cutoff. PRs whose outcome window crosses a cutoff are purged (removed), because
their label would leak information from a later period into an earlier one.

## Why the split sizes matter
The model learns only from the train split. The validation split is used once, to pick the
decision threshold (best F1). The test split is used once at the end to report results.
With very few PRs per split, one mistake changes the scores a lot, so results are reported
with bootstrap ranges.
