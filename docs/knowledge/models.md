# Models

## GNN (structure model)
The GNN is a relation-aware GraphSAGE network with two message-passing layers over a
heterogeneous code graph. In the current version (v5) the graph has seven node types:
module, class, function, method, external module, external callable and global variable
(a module-level variable). Its relations are CONTAINS, IMPORTS, CALLS, INHERITS and
ACCESSES_GLOBAL (a function or method reading or writing a module-level variable); v3 and v4
had no global variables. Every node has numeric features such as lines of code, parameter
counts, cyclomatic complexity and in/out degrees; features are log-transformed and
standardised with statistics from the training PRs only. After message passing, the node
vectors in the files the PR touched and their direct (one-hop) neighbours are averaged into
a 32-number vector per PR, as in v4. The earlier version (v3) took two averages, one over the
whole repository and one over the touched files, giving 64 numbers (32 + 32).

## Pre-merge history (v5)
v5 also gives the GNN's classifier 13 numbers about the touched code's recent past, all
measured before the merge: how fast the touched modules gained links over the previous six
months compared with their project, whether they joined a cycle then, their current coupling
and cycle share, the project's size and mean coupling, and how many commits and authors
changed the touched files in the previous 182 days. These are joined to the graph vector
before the final layer. They use no information from after the merge.

## Seeds
The v5 GNN is trained five times with different random seeds, and its reported risk score is
the mean of the five. The edge explanations (Integrated Gradients) come from the seed-1 model
alone, so the risk score inside an explanation file can differ slightly from the PR's
reported score.

## CodeReviewer (diff model)
CodeReviewer (microsoft/codereviewer) is a pretrained T5 model trained on real code-review
diffs; only its encoder is used and it is never retrained here. The diff is filtered to the
same production Python files the graph analyses (tests and docs are skipped), changed lines
are marked with add/del/keep markers, and long diffs are read in overlapping 512-token
windows (at most 32 windows). The token vectors are averaged into one 768-number vector per
PR. Re-encoding the same diff always gives the same vector. On its own it is shrunk with PCA
(fitted on training PRs only) and classified with logistic regression.

## Fusion model
In v5, fusion is late fusion: the GNN's and CodeReviewer's risk outputs are combined as a
weighted sum of log-odds, with the weight chosen on the validation projects. Validation gave
CodeReviewer a weight of 0, so in v5 the fusion model is the same as the GNN alone. In v3 and
v4, fusion joined the PCA-shrunk GNN and CodeReviewer vectors and trained one class-balanced
logistic regression. In every version the decision threshold is the one with the best F1 on
the validation split, and four models are reported side by side: always-risky (a baseline
that calls every PR risky), GNN only, CodeReviewer only and fusion.

## What the risk score means
The risk score is a model output between 0 and 1, not a calibrated probability. A score of
0.8 does not mean an 80 percent chance that the code degrades. Compare PRs by their scores and
use the threshold for the risky / not risky decision.
