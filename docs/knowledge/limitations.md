# Limitations

## Small dataset
The current dataset is small and comes from four related Pallets projects (Flask, Jinja,
Click and Werkzeug), and the test repository has only a few dozen PRs, so every score has a
wide uncertainty range. Reported results should be read together with their bootstrap ranges and
compared with the always-risky baseline. A model that does not beat that baseline has not
shown predictive value yet.

## Shortcuts the GNN may have learned
The labels partly follow simple facts such as when a PR was merged, how big the repository
is and how much of the graph a PR touches. Shortcut baselines that use only those facts are
trained next to the GNN; the shortcut-check card has their results. In v4 the GNN averages
only the touched files and their direct neighbours, but a merge-date-and-repository-size
baseline still ranks the test PRs better than the GNN, so the GNN is not yet validated
evidence that it learned structural risk. Layer C still shows how much of each structure
score comes from files the PR did not touch.

## Fusion fits the training repositories much better than new ones
Fusion scores much higher on the training PRs than on the validation and test PRs (the model
card lists F1 on train, validation and test). With so few training PRs, the structure
features let it memorise the training projects, while the frozen CodeReviewer diff features
carry over to a new repository better. More repositories and better structure features are
the next steps.

## Labels are a proxy
Labels record whether a reviewed architectural refactor touched the same files within six
months. That is evidence of later architectural work in the same area, not proof that the
PR caused it, and some refactors may be missed or mislabelled by the review process.
