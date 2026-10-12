# AI Architecture Guardian

## What the project does
AI Architecture Guardian looks at a merged Python pull request (PR) and estimates the risk
that the code area it touched will need an architectural refactor within the next six
months. It combines two views of the PR: the structure of the code before the PR (a graph
model, the GNN) and the change itself (the diff, read by the CodeReviewer model). A fusion
model joins both into one risk score, and three explanation layers show why a PR got its
score. A chatbot answers questions using only these real outputs.

## Pipeline steps
1. Collect merged PRs from GitHub and filter them.
2. For each PR, take the code just before the PR (the first-parent snapshot) and analyse it
   with Python's AST: modules, classes, functions, methods, imports, calls and inheritance.
3. Turn that analysis into a dependency graph with 15 numeric features per node.
4. Convert it to a PyTorch Geometric heterogeneous graph (six node types).
5. Label each PR from what happened in the six months after it (see "Labels").
6. GNN: a relation-aware GraphSAGE model turns the graph into a 64-number vector.
7. CodeReviewer: reads the PR's diff and turns it into a 768-number vector.
8. Fusion: shrinks both vectors with PCA and predicts risk with logistic regression.
9. XAI: explains each PR's score in three layers (structure vs diff, diff hunks, code files).
10. Chatbot: answers questions from the outputs above, citing its sources.

## Team ownership
The data collection, labels and GNN were built by one teammate; the CodeReviewer
embeddings, fusion model, XAI and chatbot by another. The dashboard is a separate part
that only reads the chatbot's outputs.
