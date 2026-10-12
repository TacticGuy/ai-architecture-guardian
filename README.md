# AI Architecture Guardian — PR Graphs and GNN Risk Prediction

This repository implements flowchart points **1–5** and a GNN encoder, training
command, inference command and embedding exporter for **6–8**. The historical
dataset and evaluation are being corrected before the next training run.

The locked static-analysis pipeline is:

```text
1. Clone and store Python repositories
2. Parse Python source with AST
3. Build a static dependency graph
4. Create explainable node features
5. Convert each graph to PyTorch Geometric HeteroData
```

The repository also includes PR scraping, historical Git snapshots, structural
graph comparisons, reviewed future-refactor labeling and GNN risk scores.
CodeBERT, fusion, XAI, RAG, LLM remediation and the dashboard are not implemented
in this branch.

The existing 107-sample checkpoint is a development model. Its dataset has
repository, year and refactor-event concentration. Its randomly split metrics
do not establish predictive value. Corrected labels, temporal evaluation and
baseline comparisons are required before reporting a final result.

## Architecture

```text
repositories.json → GitHub GraphQL → raw PR JSONL → filtering
                                                  ↓
config/repositories.json → Git clone → AST facts → dependency graph → node features → PyG HeteroData
```

- The GitHub path stores merged PR metadata and applies the configured impact/keyword filters.
- The static-analysis path clones configured repositories, parses source without importing or executing it, creates typed graph nodes/edges, and writes deterministic numeric features.
- Every clone is recorded with its HEAD commit in a manifest. Every analysis artifact is JSON and is atomically written.

## Static-analysis outputs

For a cloned repository such as `django/django`, the project creates:

```text
data/repositories/django/django/               local Git clone
data/repositories/clone_manifest.json          clone URL, HEAD commit, branch, timestamp
data/analysis/django__django/ast.json          AST symbols, imports, calls, parse errors
data/analysis/django__django/dependency_graph.json
data/analysis/django__django/node_features.json
data/pyg/django__django/graph.pt               PyTorch Geometric HeteroData (point 5)
```

These runtime files are deliberately Git-ignored: clones can be large and analysis output is reproducible.

### AST extraction (point 2)

The parser recursively finds eligible `.py` files and never executes repository code. It records:

- module, class, function, and method nodes;
- source path and line range;
- class base names;
- imports;
- static call names;
- function parameter counts;
- McCabe-style cyclomatic complexity;
- docstring and async flags;
- parse errors without failing the entire repository.

By default it skips test directories, common virtual environment/build/cache directories, `docs/`, `doc/`, `examples/` and `benchmarks/` folders, and `setup.py`/`conftest.py` files, so the graph describes the library itself. This is configurable under `static_analysis` in [config/settings.json](config/settings.json) (`excluded_directory_names`, `excluded_file_names`).

### Dependency graph (point 3)

`dependency_graph.json` contains typed nodes and these directed edges:

- `CONTAINS`: module → class/function and class → method;
- `IMPORTS`: a symbol scope → imported local/external module;
- `CALLS`: a symbol scope → locally resolved or external callable;
- `INHERITS`: a class → its parent class (project class, or an external class stored as an `external_callable` node). Built-in parents such as `object` or `Exception` are skipped.

Resolution is intentionally conservative. Ambiguous call names remain external nodes rather than being guessed.

### Node features (point 4)

Each graph node has named, ordered feature values in `node_features.json`:

- node type;
- lines of code;
- parameter counts;
- vararg/keyword-argument flags;
- cyclomatic complexity;
- docstring/async flags;
- base-class count;
- total, import, call, and containment in/out degrees.

The artifact includes both `feature_names` and a `features` mapping, so features are inspectable before any later ML conversion.

### PyTorch Geometric graphs (point 5)

`src/ml/hetero_data.py` converts `dependency_graph.json` + `node_features.json` into a PyTorch Geometric `HeteroData` object, saved as `data/pyg/<owner>__<name>/graph.pt`. The schema is fixed, so graphs from different repositories or commits can be batched together:

- **6 node types**, always present (possibly empty): `module`, `class`, `function`, `method`, `external_module`, `external_callable`.
- Each node type has `x`, a float32 tensor `[num_nodes, 15]` (columns listed in `data.feature_names`; the `node_type` column is dropped because the store already gives the type), and `node_ids`, the original node IDs in row order for mapping results back to code.
- **41 edge types**, always present (possibly empty), named `(source type, relation, target type)` such as `("module", "IMPORTS", "module")`, `("method", "CALLS", "function")` and `("class", "INHERITS", "class")`. Each has `edge_index`, an int64 tensor `[2, num_edges]`.
- Values are raw (not scaled) and no reverse edges are added: both are training choices for the GNN step.

Load a saved graph with `src.ml.hetero_data.load_hetero_data(path)`. PyTorch 2.6+ needs `weights_only=False` for `HeteroData`, which this helper sets, so only load `.pt` files this project created.

## Requirements and setup

Use Python 3.10+ (Python 3.11 is preferred), Git on your `PATH`, and a GitHub Personal Access Token only if you will use the GraphQL scraper.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `GITHUB_TOKEN=` in `.env` only for GitHub metadata scraping. Repository cloning uses public `https://github.com/owner/name.git` URLs and does not read the token.

## Run and test points 1–5

First run the offline test suite:

```powershell
python -m pytest tests -v
```

Clone one repository:

```powershell
python scripts/clone_repositories.py --repo django/django
```

Analyse that clone through points 2–4:

```powershell
python scripts/analyse_repositories.py --repo django/django
```

Convert the analysis to a PyTorch Geometric graph (point 5):

```powershell
python scripts/build_pyg_graphs.py --repo django/django
```

Inspect the outputs:

```powershell
Get-Content data/repositories/clone_manifest.json
Get-Content data/analysis/django__django/ast.json
Get-Content data/analysis/django__django/dependency_graph.json
Get-Content data/analysis/django__django/node_features.json
```

To process every enabled repository:

```powershell
python scripts/clone_repositories.py --all
python scripts/analyse_repositories.py --all
python scripts/build_pyg_graphs.py --all
```

Existing clones are left unchanged by default. Update them only explicitly:

```powershell
python scripts/clone_repositories.py --all --update
```

To analyse a local repository that is not in `repositories.json`:

```powershell
python scripts/analyse_repositories.py --path C:\path\to\repository
```

Add `--include-tests` if test code must become part of the graph.

## Existing PR-metadata workflow

With `GITHUB_TOKEN` set:

```powershell
python scripts/test_github_connection.py
python scripts/scrape_prs.py --repo django/django --max-prs 10
python scripts/filter_prs.py
python scripts/generate_statistics.py
python scripts/validate_dataset.py
```

Use `--resume` to continue a metadata scrape from its saved cursor. See `--help` on every script for arguments.

## Limits

Static analysis is syntactic and static: it cannot fully resolve dynamic imports,
reflection, monkey patching, or all attribute calls. It deliberately does not
execute target code. Each Step-5 graph represents a repository snapshot. The
historical dataset builder adds PR metadata and touched-node masks outside the
locked pipeline.

## GNN workflow and current status

The current builder creates this input for each historical PR:

```text
PR merge SHA → first-parent base snapshot → locked Steps 2–5
             → heterogeneous graph + touched-node masks
             → GraphSAGE → pooling → graph embedding → auxiliary classifier

PR base/merge diff → diff.patch → future CodeBERT encoder
```

The encoder uses two heterogeneous GraphSAGE message-passing layers by default.
It mean-pools all node embeddings and separately pools the nodes defined in files
touched by the PR. With `hidden_channels=32`, concatenating those pools produces
a **64-dimensional vector per PR**. The auxiliary classifier maps that vector to
one logit. The embedding exporter returns the vector before this classifier.

The existing input is the **before-PR graph**. Choosing candidate/head graphs or
paired base/candidate graphs to represent the proposed architectural change is
still pending. That input contract must be frozen before building the final
dataset and training both GNN and fusion. Future outcome evidence belongs in
labels and audit metadata, never in graph features or the diff encoder input.

| Flowchart area | Current branch |
| --- | --- |
| 1–5: AST, dependency graph, node features, HeteroData | Implemented; locked |
| Historical Git snapshots, diffs, graph metrics | Implemented |
| Reviewed outcomes and coverage validation | Implemented; real coverage/reviews still required |
| 6–8: heterogeneous GNN, pooling, embedding | Implemented |
| 9: Python PR diff artifacts | Implemented |
| 10–11: CodeBERT and code embedding | Teammate work; not integrated |
| 12: fusion classifier | Pending |
| 13: score for a prepared graph | Implemented; current model is a smoke model |
| New PR/branch preparation command | Pending |
| 14–18: XAI, attributed subgraph, KB, RAG, explanation | Pending |
| Dashboard and benchmark comparisons | Pending |

## Prediction target and label evidence

The current target is a future **architectural refactor in the area touched by
the PR**, observed during the following six calendar months. It is an outcome
proxy. A later file-overlapping refactor does not prove that the earlier PR
caused architectural debt.

Protocol v2 requires:

1. A completed collection covering the sample's entire six-month future window.
2. A reviewed architectural event tied to the exact merge SHA and production
   Python files, with a rationale and evidence references, for a positive label.
3. No unresolved overlapping production-Python PRs during that window for a
   negative label.
4. Complete follow-up for both classes. An early observed positive is censored
   until its six-month window is complete, just like a potential negative.
5. Unknown labels for missing coverage, unresolved reviews or failed outcome-file
   extraction. These records cannot become training negatives.

PR titles and messages may help find review candidates. They cannot make a PR
positive or negative. A review must explain the architectural change using the
diff or structural evidence. The operational criteria for accepting those
reviews still need to be established against actual historical PRs. Recording
a rationale provides traceability; it does not independently prove the review
is correct.

The original impact/semantic filtering scripts are useful for candidate discovery
and statistics. Their output is not final risk ground truth. Small two-file
architectural changes must not be discarded solely by the impact filter.

## Coverage and review files

The label command needs `--coverage` and `--event-reviews`. It stops without
changing outputs when either is missing.

The coverage file describes completed repository intervals:

```json
{
  "schema_version": 1,
  "repositories": [
    {
      "repo": "owner/repo",
      "window_start": "2020-01-01T00:00:00Z",
      "window_end": "2025-12-31T23:59:59Z",
      "pagination_completed": true,
      "source": "github_repository_pull_requests",
      "order": "CREATED_AT_ASC",
      "completion_reason": "connection_exhausted",
      "collected_pr_ids": ["owner/repo#123"]
    }
  ]
}
```

This is a schema example, not evidence for a real repository. In date-window
mode the collector generates the ID list, saves each completed page's cursor
in the manifest, and marks completion only after exhausting pagination or
passing the creation-date boundary. Min/max timestamps or a manually toggled
completion flag cannot establish collection coverage.

The date-window mode uses a GitHub repository connection ordered by creation
time, then filters each PR by merge date. This includes long-lived PRs opened
before the requested window. The legacy capped scrape still uses update order
and does not certify a historical interval. See [GitHub's GraphQL repository
reference](https://docs.github.com/en/graphql/reference/repos).

For example, collect the Flask pilot interval and its future outcome history:

```powershell
python scripts/scrape_prs.py --repo pallets/flask --window-start 2020-01-01T00:00:00Z --window-end 2026-10-10T23:59:59Z --verbose
```

Outputs are `data/raw/raw_prs_v2.jsonl` and `data/raw/coverage_v2.json`. The
manifest doubles as the resumable checkpoint. Re-run the same command after
an interruption; it continues from the last persisted page. Use `--max-pages 1`
for a partial API check: its coverage stays incomplete and the command returns
a non-success exit code until the window is finished. Sequential repository
runs with the same bounds can append to the same file pair. Do not run concurrent
collectors against those files.

`--fresh` in window mode restarts only that repository's traversal, preserving
raw data and other repository coverage. For different bounds on a repository
already present in the manifest, choose a new `--raw-output`/`--coverage` file
pair. Commit-message bodies are deliberately not paginated in window mode;
`commit_metadata_complete` stays false. Architectural reviews use actual diffs
and structural evidence rather than those messages. Base branch name, head SHA,
merge SHA and commit count are retained for subsequent snapshot validation.

The Flask pilot completed on 2026-10-11 with 645 unique PR records in this window,
640 with six-month follow-up by date, and no missing merge SHAs. These are
metadata counts, not reviewed training labels or built graphs. The data includes
default and release branches; branch/commit ancestry must be checked before
matching future outcomes across PRs. Branch names alone cannot resolve renames
such as `master` to `main`.

The review JSONL has one object per reviewed PR. An approved event has:

```json
{
  "sample_id": "owner/repo#123",
  "merge_commit_sha": "FULL_SHA_FROM_THE_COLLECTED_PR",
  "decision": "architecture_refactor",
  "reviewer": "reviewer-identifier",
  "rationale": "Describe the demonstrated architectural change",
  "evidence_refs": ["diff-or-structural-evidence-reference"],
  "affected_python_files": ["src/package/service.py"]
}
```

Other decisions are `non_architectural` and `uncertain`. A non-architectural
decision also requires a reviewer, rationale and evidence references. Missing
reviews and uncertain decisions remain unresolved. An affected file must be in
the production-Python paths actually changed at the reviewed commit.

## Corrected dataset and training commands

Run commands from the repository root with the virtual environment active.
The following corrected workflow is conditional on completed coverage and real
outcome reviews. Finishing a metadata scrape does not establish those reviews
or the final training labels.

```powershell
python scripts/label_future_refactors.py --repo pallets/flask --coverage data/raw/coverage_v2.json --event-reviews data/labels/flask_event_reviews.jsonl
python scripts/build_future_pr_dataset.py
```

New outputs are separate from the existing smoke dataset:

```text
data/labels/future_refactor_labels_v3.jsonl
data/statistics/future_refactor_audit_v3.jsonl
data/future_pr_samples_v3/<owner>__<repo>/<pr>/
    metadata.json
    diff.patch
    before/
        ast.json
        dependency_graph.json
        node_features.json
        graph.pt
```

`metadata.json` preserves the sample ID, label protocol, coverage interval,
outcome horizon, triggering event and evidence. The builder refuses to silently
reuse samples whose saved labels/evidence no longer match the current label file.
Use a new output directory for a revised cohort instead of overwriting it.

Training requires verified v2 metadata and two explicit UTC cutoffs. Choose
these after inspecting repository/date/event distributions; do not choose them
by test performance. Replace the placeholders before running:

```powershell
python scripts/train_gnn.py --train-cutoff "TRAIN_CUTOFF_UTC" --validation-cutoff "VALIDATION_CUTOFF_UTC" --epochs 50 --output models/gnn_reviewed.pt --metrics data/statistics/gnn_reviewed_metrics.json
```

The split rules are:

- Train: all six-month outcomes are known by the training cutoff.
- Validation: PRs merge after the training cutoff and their outcomes are known
  by the validation cutoff.
- Test: PRs merge after the validation cutoff and have complete follow-up.
- Purge the samples between these intervals whose future labels would not yet
  be known. A triggering refactor event cannot appear across splits.

Every split must contain both outcome classes. Training fits the feature scaler
only on training graphs, selects the epoch and decision threshold using
validation, and reports test metrics. Checkpoints save the exact PR IDs in each
split. Random stratification is available only through explicit `--allow-smoke`.

The current script keeps all training/validation/test graphs in CPU memory.
Measure memory usage before a large run; large repository graphs may require a
streaming training loader. Export already processes graphs in bounded batches.

## Class balance and evaluation

The goal is a representative, diverse dataset with enough independent positives.
An equal positive/negative count alone does not remove repository, year, file or
refactor-event bias. Repeating positives from one large refactor does not add
independent evidence.

The current training loss weights positives using the negative/positive ratio
computed from the training split. That allows learning from an imbalanced cohort
without discarding valid negatives. If balanced sampling is added later, it
belongs only in training; do not automatically combine it with the same class
weighting or apply it to validation/test. Preserve natural held-out prevalence
so false-positive rates and precision remain meaningful.

Before claiming useful prediction, compare against majority, repository/time,
touched-file historical-hotspot and graph-metric baselines. Report a temporal
test and a within-repository test, with sample counts and event concentration.
Those baseline experiments are still pending.

Metrics include precision, recall, F1, confusion counts and average precision.
Equal prediction scores enter the precision/recall curve at the same threshold;
the metric never breaks ties using labels. The `pr_auc_average_precision` field
is average precision, not trapezoidal PR area. Evaluate uncertainty when the
test contains few positives. A successful pipeline or passing unit test is not
evidence that the model generalizes.

The sigmoid output is currently uncalibrated. `risk_percent` is the score times
100, not a validated real-world probability. Calibration and a baseline-backed
assessment are needed before interpreting it as a chance of future remediation.

## GNN embedding handoff for fusion

For a newly trained checkpoint with saved split IDs:

```powershell
python scripts/export_gnn_embeddings.py --checkpoint models/gnn_reviewed.pt --output artifacts/gnn_embeddings.pt --device cpu
```

The exporter writes:

```text
artifacts/gnn_embeddings.pt      tensor bundle
artifacts/gnn_embeddings.json    readable row manifest
```

Load the bundle in Python:

```python
import torch

bundle = torch.load("artifacts/gnn_embeddings.pt", map_location="cpu", weights_only=False)
sample_ids = bundle["sample_ids"]
embeddings = bundle["embeddings"]  # [number_of_PRs, 64] with hidden_channels=32
labels = bundle["labels"]
splits = bundle["splits"]
```

Join CodeBERT and GNN rows using `sample_id`, such as `pytest-dev/pytest#14105`.
Never join by directory order or assume both encoders use the same row order.
Both encoders and the fusion classifier must respect the saved split IDs.
Any supervised CodeBERT fine-tuning must also use training PRs only.

The current 107-sample checkpoint predates saved split IDs. The exporter refuses
to guess those IDs from its seed. For format development only, use:

```powershell
python scripts/export_gnn_embeddings.py --data-dir data/future_pr_samples --checkpoint models/gnn_future_risk_107.pt --output artifacts/gnn_embeddings_107_smoke_only.pt --allow-smoke --device cpu
```

This marks split membership `unknown`; it cannot support final fusion evaluation.
Regenerate embeddings after training on the corrected cohort.

## Inference on an existing prepared graph

This command verifies local loading and scoring if the sample/checkpoint exist:

```powershell
python scripts/predict_gnn.py --graph data/future_pr_samples/pallets__flask/5777/before/graph.pt --checkpoint models/gnn_future_risk_107.pt --metadata data/future_pr_samples/pallets__flask/5777/metadata.json --device cpu
```

An optional historical label is displayed for comparison. It is not supplied to
the model. Scoring a sample that may have been used during training is only a
functional check. Preparing an arbitrary open PR or candidate branch remains
a separate integration task.

## Source layout and team ownership

```text
src/analysis/                 locked AST/graph/feature pipeline
src/ml/hetero_data.py         locked Step-5 schema
src/github/, src/scraper/     GitHub metadata collection
src/filtering/               candidate discovery
src/dataset/                 snapshots, comparisons and outcome protocol
src/ml/gnn_data.py           touched masks, sample discovery, temporal split
src/ml/hetero_gnn.py         encoder, pooling, auxiliary classifier, metrics
src/ml/gnn_inference.py      checkpoint/scaler loading and inference
src/ml/gnn_embeddings.py     fusion embedding export
scripts/                    thin commands for each workflow stage
tests/                      project tests
artifacts/                  generated fusion handoff files
```

GNN work belongs in dataset/ML modules and their commands. CodeBERT should use
separate semantic modules and `diff.patch` plus the shared sample/split contract.
Fusion consumes the encoder outputs; it should not change the locked graph
schema. Keep tokens, cloned repositories, graph datasets, model checkpoints and
generated embedding bundles out of Git.

## Historical Git evidence audit (no labels)

Before labelling, inspect a completed collection against its local clone:

```powershell
python scripts/audit_pr_history.py --repo pallets/flask
```

After reviewing and saving event decisions, corrected protocol-v3 commands are:

```powershell
python scripts/label_future_refactors.py --repo pallets/flask --coverage data/raw/coverage_v2.json --event-reviews data/labels/flask_event_reviews.jsonl
python scripts/build_future_pr_dataset.py --repo pallets/flask --max-positive 100 --max-negative 100
python scripts/train_gnn.py --train-cutoff YYYY-MM-DDTHH:MM:SSZ --validation-cutoff YYYY-MM-DDTHH:MM:SSZ
```

The cutoff placeholders must be chosen from the labelled cohort dates; do not
copy them literally. Protocol v3 verifies merge ancestry, the integrated PR
boundary, and unchanged file paths through the target branch before assigning
outcomes. A machine review can mark a PR non-architectural only when every
changed production Python file has identical executable ASTs after dropping
literal docstrings. Other machine/human-uncertain PR outcomes remain unknown.
The 107 old graphs/checkpoint are preserved for smoke demonstrations; retraining
defaults to new v3 labels, graphs and checkpoint filenames.

This command adds no risk labels and does not switch the clone's checkout. It
includes deleted files and both rename paths, respects the locked production
Python scope, and parses changed source without executing repository code.
Import/declaration changes are review evidence, not automatically architectural
refactors. A non-shallow clone can still lack source contents (`blob:none`);
the audit detects missing objects and stops rather than marking failed reads safe.
For an existing dataset clone, download missing historical contents explicitly:

```powershell
git -C data/repositories/pallets/flask fetch --refetch --no-filter origin
git -C data/repositories/pallets/flask fetch --refetch --no-filter origin '+refs/tags/*:refs/tags/*'
```

Generated reports (ignored by Git):

```text
data/statistics/pallets__flask_history_audit.jsonl
data/statistics/pallets__flask_history_audit_summary.json
```

The 11 October 2026 Flask pilot inspected 645 PRs in the completed window:

| Check | Count |
| --- | ---: |
| Production Python changes in the examined diff | 260 |
| Production changes with complete six-month follow-up by date | 256 |
| Production changes passing basic boundary/count/follow-up checks | 250 |
| Merge boundary verified against PR head (all PRs) | 569 |
| Single-commit integration boundary (all PRs) | 54 |
| Ambiguous multi-commit squash/rebase boundary (all PRs) | 22 |
| Git/GitHub changed-file count disagreements (all PRs) | 5 |

These are **not final training-sample counts**. There are six production-changing
PRs among the 22 ambiguous integrations. A multi-commit rebase cannot be safely
represented by just the last commit's parent. Matching file counts alone does
not resolve that uncertainty. Source parse failures in this pilot: zero.

Of 1,792 potential later-change pairs matching dates and production paths,
130 do not share the required commit ancestry. Another 712 have different branch
names but do share ancestry. Neither date/path overlap nor equal branch names is
a sufficient lineage check. These pairs are arbitrary changes, not reviewed
refactor outcomes. See [Git's ancestry test](https://git-scm.com/docs/git-merge-base).
Tracking file identity across intervening renames is still required before
certifying negative outcomes.

Small **proposed event-review examples**, based on inspected diffs:

| PR | Proposed event interpretation | Actual change evidence |
| --- | --- | --- |
| Flask #3709 | Architectural refactor candidate | Extracts `Scaffold`; `Flask` and `Blueprint` use the shared base; imports and shared responsibilities move. |
| Flask #5127 | Architectural refactor candidate | Separates Sans-IO bases from I/O implementations and moves scaffold code into `sansio`. |
| Flask #3739 | Non-architectural event | Changes one word in a `Blueprint` docstring; not an executable dependency or responsibility change. |
| Flask #4692 | Needs a frozen inclusion rule | Introduces a JSON-provider boundary alongside functionality/extensibility changes: mixed feature/refactor. |
| Flask #5799 | Uncertain under architecture-only scope | Changes generator/context handling; the title's word "refactor" does not establish an architectural restructuring. |
| Flask #4748 | Reconstruction uncertainty | Examined final integration diff is documentation-only, but its five-commit PR has an ambiguous boundary. |

These examples are not automatically approved event reviews, expert judgements,
or positive/negative training labels. An architectural event can label earlier
PRs through a validated future-overlap relationship; the event itself is not
automatically a positive sample. The labeller still needs integration-boundary,
ancestry and rename safeguards wired in before final labels are generated.

## Verification and remaining work

Run only this project's tests; cloned repositories contain unrelated test suites:

```powershell
python -m pytest tests -q --basetemp .venv/pytest-project-check
```

Tests exercise graph conversion, Git snapshots, label censoring, coverage and
review checks, temporal purging, tied-score metrics, model execution and keyed
embedding export. They validate software behavior; dataset validity additionally
requires review of the real collected PRs and events.

The next work is complete historical collection, an evidence-based event
definition, the final graph-input contract, a diverse cohort, temporal baseline
experiments, GNN/fusion training, score calibration and live-PR preparation.
XAI, RAG, benchmark comparisons and dashboard integration follow the agreed
encoder/label interface. No reliable final checkpoint has been trained yet.

## Dashboard

A Streamlit dashboard shows the fusion results, every PR's explanation and the
chatbot in one page.

```text
pip install -r requirements.txt
python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v3.json
streamlit run dashboard/app.py
```

Tabs: **Overview** (four models side by side with bootstrap ranges, warnings,
every test PR's risk score against the threshold, dataset splits and purged PRs),
**PR explorer** (score, true label, correct or wrong, and XAI layers A, B and C)
and **Ask the chatbot** (grounded answers with their sources; needs `GROQ_API_KEY`
in `.env`). Browsing works without a Groq key.

Editing it: wording, colours and sizes are in the `SETTINGS` block at the top of
`dashboard/app.py`; the light/dark theme is in `.streamlit/config.toml`. The
dashboard reads data only through `src/rag/api.py` (`Chatbot`), never from the
data folders directly, so changing the page cannot change the pipeline. The
colour pairs were checked for colour-blind safety and contrast; keep each pair
together. `tests/test_dashboard.py` runs the app headless on test data.
