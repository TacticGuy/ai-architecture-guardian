# Explanations (XAI)

## Layer A: structure versus diff
Layer A splits a PR's fusion score into a structure part (from the GNN vector) and a diff
part (from the CodeReviewer vector). Each part is how much the score's logit changes when
that input is replaced by the training average. For logistic regression the parts add up
exactly: base + structure + diff = logit. A positive part pushed the risk up; a negative
part pushed it down.

## Layer B: which diff hunks matter
A hunk is one block of changed lines in a diff (it starts with @@). Layer B hides one hunk
at a time, re-encodes the diff with CodeReviewer and re-scores the PR. The drop in risk is
the hunk's effect: positive means that hunk pushed the risk up. Only hunks in production
Python files are tested, and at most the 20 largest hunks per PR. If a hunk is the PR's only
production change, it is compared with having no diff information at all.

## Layer C: which code files matter
Layer C uses Integrated Gradients on the GNN. It starts from a neutral graph (same nodes and
edges, but every node looks like an average training node), moves to the real graph in small
steps and adds up how much each node moved the fusion score. Node amounts are summed per
source file; library nodes are grouped as external modules and external callables. Each
file is marked as touched or not touched by the PR. The amounts add up to the difference
between the real and the neutral score.

## How to read the explanations
Explanations show what the model relies on, not proof of what causes risk. When the model
itself performs poorly, its explanations describe a poor model. Safety checks stop the
explanation run if the saved vectors cannot be reproduced exactly from the code, so the
explanations always belong to the model that produced the scores.
