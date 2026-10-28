# XAI-grounded design-principle retrieval and evaluation

## Method

The v5 classifier reads a Python pull request in two ways: its code diff and
the repository dependency graph with that PR applied. Its explanation step
attributes part of the risk score to specific graph nodes and edges. Our RAG
component begins with that attribution file. It does not simply search for
words from a reviewer question. A deterministic signature function reads the
highest-attributed edges, touched modules, coupling counts, and cycle flags.
It marks evidence tags such as `added_dependency`, `cross_module_call`,
`global_state`, or `mutual_import`. Positive attribution determines each tag's
weight; the weights are normalized. This keeps the retrieval input connected
to the model's actual evidence rather than a broad description of the PR.

We wrote 50 short design cards in our own words. Each card names a principle,
smell, or refactoring and lists graph signals and relation types that could
make it relevant. The cards draw on Martin's dependency and package principles,
Fowler's refactoring catalogue, and Python's protocol and import guidance
(Martin; Fowler; Python Software Foundation; PEP 544). The main retriever
scores cards by overlap with the weighted evidence tags. Matching edge types
add a small bonus; BM25 over a text rendering of the evidence breaks ties.
The returned card records *why* it matched. Our comparison retriever instead
uses ordinary BM25 on the PR title and changed-code text. This comparison
tests whether graph-attribution retrieval adds value beyond lexical matching.

The language model receives a deliberately small evidence packet: the title,
score and threshold, the base, structure-GNN, history, and diff contributions,
recent change-history features for the touched files, a few strongest positive
and negative edges, coupling values for touched modules, two code hunks, and up
to three retrieved cards. It must return JSON with a verdict,
plain-English explanation, edge citations, principle IDs, and a minimal
refactoring suggestion. A checker rejects references to edges absent from the
attribution file, principles absent from the retrieved cards, and numbers not
present in the input. The model gets one repair attempt, and every violation
is recorded. A rejected answer remains a failed output rather than being
silently accepted. For a low-risk PR, the system may say no refactor is
justified; the risk score is not presented as a calibrated probability.

## Evaluation design

The reference set is drawn only from held-out projects. With a fixed random
seed, we selected 20 predicted-degrading and 20 predicted-safe PRs.
For each one, a human reviewer reads the attribution and the actual GitHub
diff, then writes a reference explanation and smallest plausible fix, and
marks relevant principle-card IDs. Generated outputs are not used to write
these references. The three systems are attribution-signature retrieval,
title-and-diff BM25 retrieval, and no retrieved cards. This ablation separates
the benefit of the retrieval source from that of giving the model any cards.

We compare each generated explanation with its reference using BERTScore
precision, recall, and F1, which measures contextual-token similarity, and
ROUGE-1, ROUGE-2, and ROUGE-L F-measures, which measure word-sequence overlap
(Zhang et al.; Lin). Neither metric proves that a technical statement is true.
We therefore also measure principle precision@3 and recall@3 against the
human IDs, the fraction of answers with zero grounding violations, mean
violation count, and a simple fix-actionability proxy: naming both a changed
file and a catalogue refactoring. Each mean receives a 95% percentile
bootstrap interval from 1,000 resamples. Paired Wilcoxon tests compare the
signature system with each baseline for BERTScore-F1 and ROUGE-L. We report
sample size and p-values rather than claiming significance from a small
difference alone.

For a separate blind human study, 12 of the same PRs are shown with the three
systems' explanations in independently shuffled A/B/C order. Reviewers rate
correctness, usefulness for review, actionability of the fix, and clarity from
1 to 5. We also ask whether they are students or professionals and how long
they have coded. The private order key is kept separate from the form. The
analysis reports exact respondent counts and role mix, mean and median ratings,
a Friedman repeated-measures test, Holm-corrected paired Wilcoxon comparisons,
and ordinal Krippendorff alpha for rater agreement. Survey responses are
never synthesized.

## Results and limitations

The automatic evaluation used 40 real held-out v5 PRs and 120 generated
explanations. Values below are means with 95% bootstrap intervals. Because
BERTScore was rescaled against its baseline, negative values are possible and
mean that similarity was below that baseline; they are not error values.

| Metric | Signature | Text BM25 | No retrieval |
|---|---:|---:|---:|
| BERTScore F1, mean [95% CI] | -1.627 [-2.390, -0.864] | -1.903 [-2.781, -1.147] | -0.905 [-1.539, -0.281] |
| ROUGE-L F1, mean [95% CI] | 0.115 [0.087, 0.142] | 0.107 [0.077, 0.135] | 0.134 [0.112, 0.156] |
| Principle precision@3 | 0.108 [0.058, 0.167] | 0.050 [0.008, 0.092] | 0.000 [0.000, 0.000] |
| Zero-violation grounding rate | 0.650 [0.500, 0.800] | 0.600 [0.425, 0.750] | 0.800 [0.675, 0.925] |
| Actionable-fix proxy | 0.050 [0.000, 0.125] | 0.025 [0.000, 0.075] | 0.000 [0.000, 0.000] |

Signature retrieval more than doubled principle precision@3 over text BM25
(0.108 against 0.050) and also improved recall@3 (0.125 against 0.054). It did
not outperform the no-retrieval baseline on explanation-similarity metrics.
Paired Wilcoxon tests found no significant difference between signature and
text or signature and no retrieval for BERTScore-F1 or ROUGE-L (all p-values
were above 0.17). The no-retrieval system also had the highest zero-violation
grounding rate. These results support the narrower claim that attributed graph
signals improve retrieval of human-relevant principles over lexical BM25, not
the broader claim that they make every generated explanation better. The blind
human study is prepared but has no responses yet, so no Likert results are
reported.

There are several limits to what this study can establish. Attributions
reflect model behavior, not necessarily causal reasons for future code
changes. Graph construction can miss dynamic Python behavior and may
misinterpret a type-only import. A card's tag match makes it relevant to
inspect, not automatically correct for that PR. Reference answers and Likert
ratings involve human judgment; a small sample may have wide uncertainty.
BERTScore and ROUGE can reward fluent similarity while missing an unsupported
technical claim, which is why the explicit grounding check and blind reviewer
ratings matter. Suggested fixes are hypotheses for maintainers, not patches
that have been verified to preserve behavior.

## Works cited (MLA)

Fowler, Martin. *Refactoring: Improving the Design of Existing Code*. 2nd ed.,
Addison-Wesley, 2018. [Refactoring catalogue](https://refactoring.com/catalog/).

Lin, Chin-Yew. "ROUGE: A Package for Automatic Evaluation of Summaries."
*Text Summarization Branches Out*, Association for Computational Linguistics,
2004, pp. 74-81. https://aclanthology.org/W04-1013/.

Martin, Robert C. "Design Principles and Design Patterns." 2000.

Python Software Foundation. "The Import System." *Python Documentation*,
https://docs.python.org/3/reference/import.html. Accessed 27 Oct. 2026.

"PEP 544 - Protocols: Structural Subtyping (Static Duck Typing)." *Python
Enhancement Proposals*, https://peps.python.org/pep-0544/. Accessed 27 Oct. 2026.

Zhang, Tianyi, et al. "BERTScore: Evaluating Text Generation with BERT."
*International Conference on Learning Representations*, 2020,
https://arxiv.org/abs/1904.09675.
