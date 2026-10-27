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
6. GNN: a relation-aware GraphSAGE model turns the touched files and their direct
   neighbours into a 32-number vector (v4).
7. CodeReviewer: reads the PR's diff and turns it into a 768-number vector.
8. Fusion: shrinks both vectors with PCA and predicts risk with logistic regression.
9. XAI: explains each PR's score in three layers (structure vs diff, diff hunks, code files).
10. Chatbot: answers questions from the outputs above, citing its sources.
11. Web app: a React front end and a FastAPI back end show the results, every PR's
    explanation, live analysis of any public GitHub PR, and the chatbot.

## Team ownership
The team has three members. Sai Praveen Moturi built the PR collection, filtering,
repository cloning and the static analysis (AST extraction, dependency graph and node
features), and the React and FastAPI web app. Shynaa Chopra, the team leader, built the
before/after PR snapshots, the reviewed labels and the GNN, including the v4 repository
holdout, the shortcut baselines and live GitHub PR analysis. V Harsha Sai Vallumkonda built
the PyTorch Geometric graph conversion, the CodeReviewer embeddings, the fusion model, the
three explanation layers, the knowledge base, the chatbot and its evaluation, and run_all.
The web app only reads the project outputs, so it cannot change the pipeline.
