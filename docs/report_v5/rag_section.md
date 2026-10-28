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
seed, we selected 20 predicted-degrading and 20 predicted-safe PRs. For each
one, a reference explanation, the smallest plausible fix and the relevant
principle-card IDs were written from the attribution file and the actual GitHub
diff. **These 40 references were drafted by a language model (Codex); review by
a team member is [pending / completed on DATE].** Generated outputs were not
used to write them. Because the references are LLM-drafted, BERTScore and ROUGE
measure agreement with a model-written reference, not with an independent human
expert; the blind developer study below is the human evaluation. The three
systems are attribution-signature retrieval (ours), title-and-diff BM25
retrieval, and no retrieved cards. This ablation separates the benefit of the
retrieval source from that of giving the model any cards.

We compare each generated explanation with its reference using BERTScore
precision, recall and F1 (rescaled against its baseline), which measures
contextual-token similarity, and ROUGE-1, ROUGE-2 and ROUGE-L F-measures, which
measure word-sequence overlap (Zhang et al.; Lin). Neither metric proves that a
technical statement is true. We therefore also measure principle precision@3
and recall@3 against the reference principle IDs, and a simple
fix-actionability proxy: naming both a changed file and a catalogue
refactoring. Each mean receives a 95% percentile bootstrap interval from 1,000
resamples. Paired Wilcoxon signed-rank tests compare the signature system with
each baseline.

An answer counts as valid only if it passes the grounding checker after its one
repair attempt. Systems are compared on the PRs where all three produced a
valid answer, so every system is scored on the same PRs. We report each
system's failure count separately, since the checker failures are themselves a
result.

For a separate blind human study, 12 PRs on which all three systems produced a
valid answer were chosen with a fixed seed and shown with the three
explanations in independently shuffled A/B/C order. Reviewers rate
correctness, usefulness for review, actionability of the fix, and clarity from
1 to 5, and say whether they are students, professionals or researchers and
how many years they have programmed. The private order key is kept separate
from the form. The analysis reports exact respondent counts and role mix, mean
and median ratings, a Friedman repeated-measures test, Holm-corrected paired
Wilcoxon comparisons, and ordinal Krippendorff alpha for rater agreement.
Survey responses are never synthesized.

## Results

We generated 120 explanations for 40 held-out v5 PRs. The grounding checker
rejected 7 (signature 3 of 40, text BM25 1 of 40, no retrieval 3 of 40): 3
cited edges absent from the attribution file, 2 gave a verdict that contradicts
the model's threshold, 1 stated a number not in the input, and 1 cited
principles that were not retrieved. Six PRs
lack a valid answer from at least one system, so the paired comparison uses
**34 PRs**. An earlier run required exact equality for numbers, so correctly
rounded values (0.409 for 0.408685) were rejected; we fixed the checker to
accept ordinary rounding, which raised coverage from 29 to 34 PRs. Values are
means with 95% bootstrap intervals.

| Metric (34 PRs) | Signature (ours) | Text BM25 | No retrieval |
|---|---:|---:|---:|
| **Principle precision@3** | **0.118** [0.059, 0.176] | 0.029 [0.000, 0.078] | 0.000 |
| **Principle recall@3** | **0.137** [0.074, 0.211] | 0.034 [0.000, 0.088] | 0.000 |
| **BERTScore F1** | **0.137** [0.114, 0.163] | 0.113 [0.092, 0.132] | 0.101 [0.082, 0.118] |
| ROUGE-L F1 | 0.171 [0.159, 0.184] | 0.172 [0.163, 0.181] | 0.168 [0.157, 0.178] |
| ROUGE-1 F1 | 0.286 [0.267, 0.306] | 0.286 [0.269, 0.304] | 0.294 [0.278, 0.311] |
| ROUGE-2 F1 | 0.039 [0.030, 0.048] | 0.049 [0.040, 0.059] | 0.048 [0.038, 0.057] |
| Actionable-fix proxy | 0.118 [0.029, 0.235] | 0.029 [0.000, 0.088] | 0.000 |
| Failed grounding (of 40) | 3 | 1 | 3 |

| Paired Wilcoxon test (34 PRs) | Signature vs text BM25 | Signature vs no retrieval |
|---|---:|---:|
| Principle precision@3 | **p = 0.033** (better on 10 PRs, worse on 1) | p = 0.001 |
| Principle recall@3 | **p = 0.041** | p = 0.003 |
| BERTScore F1 | p = 0.174 | p = 0.041 |
| ROUGE-L F1 | p = 0.577 | p = 0.946 |

**Retrieving on the attributed edges finds the design principles in the
references about four times as often as BM25 on the PR text** (precision@3
0.118 against 0.029; p = 0.033). This is the direct test of using graph
attributions, rather than text, as the retrieval query. The no-retrieval system
scores 0 by construction, since it is given no cards to cite. The signature
system also has the highest BERTScore F1. Its gain over no retrieval
(p = 0.041) does not survive a Holm correction for the two BERTScore
comparisons, and its gain over text BM25 is not significant (p = 0.174). ROUGE
shows no difference between the systems: the explanations use similar words,
and the difference lies in which principles and edges they cite. These results
support the narrower claim that attributed graph signals improve the retrieval
of relevant design principles over lexical BM25, not that they make every
generated explanation better. Two of the 3 signature failures cited edges that
were not in the attribution file, a reminder that the grounding check is
needed. The blind developer study is live; [N] responses had been received by
[DATE].

## Limitations

There are several limits to what this study can establish. Attributions
reflect model behavior, not necessarily causal reasons for future code
changes. Graph construction can miss dynamic Python behavior and may
misinterpret a type-only import. A card's tag match makes it relevant to
inspect, not automatically correct for that PR. The reference answers are LLM-drafted, so the automatic metrics measure
agreement with a model-written reference; with 34 PRs and a small survey,
uncertainty is wide.
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
