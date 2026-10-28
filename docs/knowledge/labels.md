# Labels and data splits

## What label 1 and label 0 mean
In the current version (v5) labels are automatic: no person reviews them. Label 1
(degrading) means that in the six months after the PR was merged, the modules it touched
gained dependency links faster than the rest of the same project, or one of them joined a
new import cycle. Label 0 (not degrading) means neither happened. The label is an outcome
proxy, not a causal claim: other PRs merged in those six months also change the touched
modules. PRs whose touched modules no longer exist six months later get no label.

## How the v5 label is computed
Each module's coupling is the number of other project modules it depends on plus the number
that depend on it (imports, calls, inheritance and shared module-level variables all count).
The growth of the touched modules is their average coupling six months after the merge minus
their coupling at the merge. The project trend is the same change for an average module of
the whole project. Excess growth is growth minus trend, so a project that was growing
everywhere does not make a PR degrading. A PR is label 1 when excess growth is above 0.5
links per module, or when a touched module is in an import cycle six months later that it was
not in at the merge.

## Why "the PR creates a cycle" is not the label
Whether a PR itself creates an import cycle can be checked exactly by a simple rule (Tarjan's
strongly connected components) at merge time, so it needs no learning. It is also rare: 3 of
260 PRs in the pilot. The v5 label asks what a rule cannot see at merge time: how the touched
code evolves afterwards.

## Earlier labels (v3 and v4)
In v3 and v4, label 1 meant that within six months a reviewed architectural refactor PR
changed the same production Python files, with the git history linking the two verified;
label 0 meant no such refactor and no unresolved overlapping PRs. Each positive needed a
human-reviewed event with a written rationale, and records with unresolved reviews got no
label. PR titles or messages alone never decided a label.

## How the data is split
In the current version (v5) the data has 6,141 PRs from 40 open-source Python projects, and
whole repositories are kept apart (a repository holdout): 24 projects for training (3,576
PRs, 1,145 degrading), 7 for validation (1,190 PRs, 403 degrading) and 9 for testing (1,375
PRs, 519 degrading). The test projects are never seen while training, which stops a model
from scoring well only because it learned one project's habits. In v4 the holdout used four
repositories (Flask and Jinja for training, Click for validation, Werkzeug for testing). In
v3 PRs were split by merge time, and PRs whose six-month window crossed a split cutoff were
removed. The dataset card lists the PRs per split and per repository.

## Why the split sizes matter
The model learns only from the train split. The validation split is used to choose settings
and the decision threshold (best F1). The test split is used once at the end to report
results. Even with v5's larger test set, scores move with the PRs that happen to be in it, so
results are reported with bootstrap ranges.
