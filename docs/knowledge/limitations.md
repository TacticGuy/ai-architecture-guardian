# Limitations

## Small dataset
The current dataset is small and comes from a single repository, so every score has a wide
uncertainty range. Reported results should be read together with their bootstrap ranges and
compared with the always-risky baseline. A model that does not beat that baseline has not
shown predictive value yet.

## Whole-repository signal in the GNN
The GNN averages over all nodes in the repository as well as the touched files. Layer C
shows that files a PR did not touch can contribute a large share of the structure score.
Because the data is split by time, this can make the model learn what the repository looked
like at a given time rather than what the PR changed. Time-only and repository-only
baselines are planned to test this.

## Labels are a proxy
Labels record whether a reviewed architectural refactor touched the same files within six
months. That is evidence of later architectural work in the same area, not proof that the
PR caused it, and some refactors may be missed or mislabelled by the review process.
