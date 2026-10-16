# Models

## GNN (structure model)
The GNN is a relation-aware GraphSAGE network with two message-passing layers over a
heterogeneous code graph with six node types: module, class, function, method, external
module and external callable. Every node has 15 numeric features such as lines of code,
parameter counts, cyclomatic complexity and in/out degrees; features are log-transformed
and standardised with statistics from the training PRs only. After message passing it
takes two averages: one over all nodes in the repository and one over the nodes in files
the PR touched. Joining them gives a 64-number vector per PR (32 + 32). The GNN also has its
own small classifier, used for its own reported scores.

## CodeReviewer (diff model)
CodeReviewer (microsoft/codereviewer) is a pretrained T5 model trained on real code-review
diffs; only its encoder is used and it is never retrained here. The diff is filtered to the
same production Python files the graph analyses (tests and docs are skipped), changed lines
are marked with add/del/keep markers, and long diffs are read in overlapping 512-token
windows (at most 32 windows). The token vectors are averaged into one 768-number vector per
PR. Re-encoding the same diff always gives the same vector.

## Fusion model
Fusion joins the GNN vector and the CodeReviewer vector for each PR by its sample id. Each
vector is first shrunk with PCA to a few numbers (fitted on training PRs only), then a
class-balanced logistic regression predicts the risk. The decision threshold is the one with
the best F1 on the validation split, the same rule the GNN uses. Four models are always
reported side by side: always-risky (a baseline that calls every PR risky), GNN only,
CodeReviewer only and fusion.

## What the risk score means
The risk score is a model output between 0 and 1, not a calibrated probability. A score of
0.8 does not mean an 80 percent chance of a refactor. Compare PRs by their scores and use the
threshold for the risky / not risky decision.
