# AI Architecture Guardian

AI Architecture Guardian predicts, **before a Python pull request (PR) is merged**, whether it
will make the code base more tightly coupled over the following six months, and explains why.

* **Input:** the repository's dependency graph with the PR applied, and the PR's diff.
* **Output:** a risk score, the dependencies (graph edges) that pushed the score up or down, and
  a plain-English explanation with a suggested minimal fix.

The graph is built from source with Python's `ast` module (no code is executed). A heterogeneous
graph neural network (GNN) scores it, Integrated Gradients attributes the score to edges, and a
retrieval-augmented LLM turns the attributed subgraph into an explanation grounded in design
principles. A React + FastAPI web app shows all of it, including live GitHub PRs.

The current version is **v5** (v5.1 for the final model). Earlier versions are summarised in
[Earlier versions](#earlier-versions-v3-and-v4).

## Contents

* [Results at a glance (v5)](#results-at-a-glance-v5)
* [How it works](#how-it-works)
* [Setup](#setup)
* [Run the web app](#run-the-web-app)
* [Live GitHub PR analysis](#live-github-pr-analysis)
* [Static analysis: points 1–5](#static-analysis-points-15)
* [The v5 dataset and label](#the-v5-dataset-and-label)
* [Train, compare and explain (v5 pipeline)](#train-compare-and-explain-v5-pipeline)
* [Explanations with RAG](#explanations-with-rag)
* [Graph validation and tool baselines](#graph-validation-and-tool-baselines)
* [Tests](#tests)
* [Repository layout](#repository-layout)
* [Limitations](#limitations)
* [Earlier versions (v3 and v4)](#earlier-versions-v3-and-v4)

## Results at a glance (v5)

**Dataset:** 6,141 merged PRs from 40 open-source Python projects. Whole projects are held out:
24 for training (3,576 PRs), 7 for validation (1,190) and 9 for testing (1,375; 519 degrading).

**Models on the 9 held-out test projects** (threshold chosen on validation, best F1):

| Model | F1 | PR-AUC | ROC-AUC | Precision in top 20% |
|---|---:|---:|---:|---:|
| Always risky (baseline) | 0.548 | 0.377 | 0.500 | 0.185 |
| CodeReviewer on the diff only | 0.550 | 0.403 | 0.545 | 0.429 |
| **GNN (ours, mean of 5 seeds)** | **0.604** | **0.632** | 0.721 | **0.687** |
| Fusion (GNN + CodeReviewer) | 0.604 | 0.632 | 0.721 | 0.687 |

Bootstrap 95% ranges for the GNN: F1 0.571–0.635, PR-AUC 0.589–0.672. Validation gave
CodeReviewer a fusion weight of 0, so fusion equals the GNN.

**Against 16 comparison models** on the same split (`artifacts/gnn_metrics_v5.json`), the GNN has the
highest PR-AUC. The closest are the CodeScene-style hotspot (0.616) and the pre-merge history
features (0.609). History has a slightly higher ROC-AUC (0.739) than the GNN. SonarQube (0.502),
pylint (0.391) and radon (0.391) score lower, as does a SonarQube-style "flag any added debt" rule
(0.384). See [Graph validation and tool baselines](#graph-validation-and-tool-baselines).

**Explanations** (34 held-out PRs, three systems): retrieving design principles from the attributed
graph signature gives the best BERTScore F1 (0.137, against 0.113 for text retrieval and 0.101
with no retrieval; p = 0.041 against no retrieval) and the best principle precision@3 (0.118
against 0.029). A blind developer survey is prepared; no responses are reported yet.

The risk score is a model output between 0 and 1, **not a calibrated probability**.

## How it works

```text
Clone repository ─► AST facts ─► typed dependency graph ─► node features ─► PyG HeteroData   (points 1–5)
                                                                                 │
merged PR ─► before / after snapshots ─► future-coupling label (6 months later)  │
          ─► pre-merge history features ──────────────────────────────┐         │
          ─► diff ─► CodeReviewer embedding ─┐                         ▼         ▼
                                             └──► late fusion ◄── heterogeneous GraphSAGE GNN
                                                       │
                     Integrated Gradients on edges ◄───┘ risk score
                                 │
          attributed subgraph ─► evidence signature ─► design-principle retrieval ─► grounded LLM explanation
```

## Setup

You need Python 3.10+ (3.11 preferred), Git on your `PATH`, and Node.js for the web app.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-validation-v5.txt
pip install scikit-learn scipy krippendorff matplotlib rouge-score
Copy-Item .env.example .env
cd web; npm install; cd ..
```

* `scikit-learn` is used by `scripts/compare_coupling_models.py`. `scipy` and `krippendorff`
  are used by the survey analysis.
* `requirements-rag-v5.txt` (BERTScore) pins `transformers<5`. Install it in a **separate**
  environment, only if you re-run the RAG evaluation, so the main app's `transformers` is not
  downgraded.
* PyCG, used only by the graph validation, needs Python 3.8–3.10 in its own environment.

`.env` keys (never commit them):

| Key | Needed for |
|---|---|
| `GROQ_API_KEY` | the chatbot and RAG explanations |
| `GITHUB_TOKEN` | the GitHub API: PR scraping, and a higher rate limit for live PRs |
| `SONAR_TOKEN` | SonarQube baseline runs only |

## Run the web app

Two terminals, from the repository root:

```powershell
uvicorn api.main:app --port 8000      # terminal 1: back end

cd web
npm run dev                           # terminal 2: front end at http://localhost:5173
```

Open <http://localhost:5173/prototype>. The dev server forwards `/api` to port 8000. For a
production build run `npm run build` in `web/` (output in `web/dist/`) and serve it with a static
host that forwards `/api` to the back end.

The **Data version** selector lists every folder `data/kb/<version>/` that has a `cards.jsonl`
(v5, v4, v3). Prototype tabs:

* **Overview**: the four models side by side with bootstrap ranges, every test PR's risk score
  against the threshold (scrollable), and the dataset splits.
* **PR explorer**: one PR's score, true label and whether the prediction was right. v3/v4 PRs show
  XAI layers A, B and C. v5 PRs point to the Attribution tab.
* **Live GitHub PR**: score a public PR (see below).
* **Ask the chatbot**: grounded answers with sources, rendered as safe Markdown (no raw HTML).
  Needs `GROQ_API_KEY`.
* **Attribution (v5)**: a searchable list of v5 PRs, and for each one the risk bar, the score split
  (base, structure GNN, pre-merge history, diff), the top 30 attributed edges as an interactive graph,
  module coupling before and after, the top diff hunks, the RAG explanation if one exists, and the
  explainer's unfaithfulness. Screenshots: `docs/screenshots_v5/`.

The back end reads data only through `src/rag/api.py`, `src/live_pr.py` and
`api/v5_attribution.py`, so the interface cannot change the pipeline. Endpoints: `/api/versions`,
`/api/overview`, `/api/prs`, `/api/prs/detail`, `/api/live`, `/api/chat`, `/api/chat/reset`,
`/api/v5/attributions` and `/api/v5/attributions/{owner}/{repo}/{number}`.

Data the app reads (all Git-ignored, shared outside Git):

```text
data/kb/<version>/cards.jsonl, kb.json      chatbot knowledge base, one per data version
data/fusion/<version>/metrics.json          model results;  predictions.csv: every PR's scores
artifacts/gnn_embeddings_<version>.json     PRs, labels and splits of a data version
artifacts/gnn_metrics_<version>.json        split per repository and the baseline check
data/xai/v5/<owner>__<repo>__<number>.json  v5 edge attributions (schema attribution_v5/1)
data/rag_v5/explanations/<same name>.json   RAG explanations (optional)
```

## Live GitHub PR analysis

```powershell
python scripts/analyze_live_pr.py --url https://github.com/pallets/click/pull/3767 --max-hunks 3
```

This scores one public PR with the trained v4 GNN, CodeReviewer and fusion model (the v5 graph's
`global_variable` nodes and `ACCESSES_GLOBAL` edges are removed to match that checkpoint). The
result is saved under `data/live/`. The **Live GitHub PR** tab does the same.

The PR's state decides which code is analysed, and never silently the wrong one:

| PR state | Analysed | `mode` |
|---|---|---|
| Open, GitHub has a test merge | GitHub's merge commit vs its first parent. If GitHub computed it against an older base, that is recorded in `base_note`. | `open_test_merge` |
| Merged (merge, squash or rebase) | the merge commit vs its first parent | `merged_pr` |
| Open, no test merge | a local merge in a temporary worktree. A conflict stops with a clear error. | `open_local_merge` |
| Closed without merging | the PR head vs its merge base, with a warning | `closed_unmerged` |

Live reports always have `label: null`: an open PR has no six-month outcome yet. They are never
added to training or evaluation.

## Static analysis: points 1–5

```powershell
python scripts/clone_repositories.py --repo pallets/flask      # 1. clone (or --all)
python scripts/analyse_repositories.py --repo pallets/flask    # 2-4. AST, dependency graph, features
python scripts/build_pyg_graphs.py --repo pallets/flask        # 5. PyTorch Geometric HeteroData
```

`analyse_repositories.py --path <folder>` analyses any local repository. Outputs (Git-ignored):

```text
data/repositories/pallets/flask/                local clone (HEAD recorded in clone_manifest.json)
data/analysis/pallets__flask/ast.json           symbols, imports, calls, parse errors
data/analysis/pallets__flask/dependency_graph.json
data/analysis/pallets__flask/node_features.json
data/pyg/pallets__flask/graph.pt
```

**Parsing** finds every eligible `.py` file and never executes it. Tests, docs, examples,
benchmarks, virtual environments, `setup.py` and `conftest.py` are skipped by default
(`static_analysis` in `config/settings.json`; `--include-tests` adds tests).

**The graph** has **7 node types**: module, class, function, method, external module, external
callable and global variable (a module-level variable). It has **5 relations**:

* `CONTAINS`: module → class, function or global variable; class → method;
* `IMPORTS`: a scope → an imported project or external module;
* `CALLS`: a scope → a resolved project callable or an external callable;
* `INHERITS`: a class → its base class (builtin bases such as `object` are skipped);
* `ACCESSES_GLOBAL`: a function, method or class → a module-level variable it reads or writes.
  Names used only in type annotations are not counted.

Resolution is conservative: ambiguous calls stay external instead of being guessed.

**Features:** every node has 15 numeric features: lines of code, parameter counts, vararg and
keyword flags, cyclomatic complexity, docstring and async flags, base-class count, and in/out
degrees per relation. `node_features.json` keeps the feature names.

**HeteroData** (`src/ml/hetero_data.py`, schema version 2) always has all 7 node stores and all
46 typed edge stores (for example `("method", "CALLS", "function")`), possibly empty, so graphs from
different repositories and commits batch together. Load a graph with
`src.ml.hetero_data.load_hetero_data(path)`. Only load `.pt` files this project created.

## The v5 dataset and label

**The label is automatic.** A PR is **label 1 (degrading)** when, in the six months after it is
merged, the modules it touched gain dependency links faster than the project's own trend, or
one of them joins a new import cycle:

* coupling of a module = modules it depends on + modules that depend on it (imports, calls,
  inheritance and shared module-level variables all count);
* growth g = the touched modules' mean coupling change; trend Δ = the whole project's mean change;
* excess growth e = g − Δ; **label 1 if e > 0.5 or a touched module joins a new import cycle**.

Subtracting the trend means a project that grows everywhere does not make a PR degrading. Whether a
PR *itself* creates a cycle is not used as the label: a rule (Tarjan) decides it with no learning,
and it occurred in only 3 of 260 pilot PRs. The full definitions and proofs are in
`docs/report_v5/math_formulations.md` and `src/dataset/future_coupling.py`.

**Pre-merge history features (v5.1):** 13 numbers per PR, all measured before the merge: the touched
modules' coupling growth over the previous six months against their project, whether they joined a
cycle then, their current coupling and cycle share, project size and mean coupling, and commits and
authors on the touched files in the previous 182 days (`src/dataset/history_features.py`).

**Split:** a repository holdout (`config/coupling_split_v5.json`). Each project is entirely in
train, validation or test.

## Train, compare and explain (v5 pipeline)

```powershell
# 1. dataset: before/after graphs, diffs and labels for every PR (local clones, no GitHub API)
python scripts/build_coupling_dataset.py --repos config/coupling_repositories.json --clones data/repositories --output data/coupling_samples_v5
python scripts/build_history_features.py --data-dir data/coupling_samples_v5 --clones data/repositories
python scripts/rebuild_v5_graphs.py --data-dir data/coupling_samples_v5 --clones data/repositories   # only after a graph-extraction fix

# 2. hand-off files: the manifest and diffs, and the Kaggle upload folder
python scripts/export_v5_files.py --data-dir data/coupling_samples_v5 --out-dir data
python scripts/pack_v5_for_kaggle.py --data-dir data/coupling_samples_v5 --out-dir kaggle_v5

# 3. diff embeddings (GPU) and GNN training, 5 seeds (notebooks/ai_guardian_v51_kaggle.ipynb runs both)
python scripts/embed_diffs_kaggle.py --diffs diffs_v5.jsonl --output-dir embeddings_v5
python scripts/train_coupling_gnn.py --data-dir data/coupling_samples_v5 --seeds 1 2 3 4 5

# 4. the GNN against every baseline on the held-out projects (writes data/comparison_v5/)
python scripts/compare_coupling_models.py --data-dir data/coupling_samples_v5

# 5. one edge-attribution file per test PR, for the Attribution tab
python scripts/explain_coupling_v5.py --data-dir data/coupling_samples_v5 --clones data/repositories --checkpoint data/gnn_v5/seed_1/model.pt --output-dir data/xai/v5 --split-name test --limit 200

# 6. results in the web app's layout, then the v5 chatbot knowledge base
python scripts/export_v5_web_bundle.py --manifest <v5_manifest.jsonl> --comparison data/comparison_v5 --gnn-dir <chosen GNN run>
python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v5.json --samples-dir data/coupling_samples_v5
```

**Model:** a relation-aware GraphSAGE GNN, with 2 layers and 32 hidden channels. It averages the
nodes in the touched files and their one-hop neighbours, adds the 13 history features, and then
classifies. Features are standardised with training statistics only. Scores are the mean of 5 seeds.

**Diff branch:** CodeReviewer (`microsoft/codereviewer`, encoder only, never retrained) reads the
production-code diff in overlapping 512-token windows. It is combined with the GNN by late fusion of
log-odds, with the weight chosen on validation.

**Explanations** (`src/xai/coupling_attribution.py`): edge-level Integrated Gradients scales every
edge's message from 0 (switched off) to 1 (the real graph). The edge numbers add up to the score
change between the two, and positive numbers push the risk up. Node-level Integrated Gradients
starts from the training-average features. GNNExplainer is a second, independent explainer.
Each file keeps the top 30 edges, the score split (layer A), the most influential diff hunks and
an unfaithfulness score (0 = the top edges alone reproduce the prediction). The files come from
the seed-1 model, so their risk score can differ slightly from the 5-seed mean.

## Explanations with RAG

`src/rag_v5/` turns an attribution file into a grounded explanation and a minimal-fix suggestion:

1. **Signature:** deterministic evidence tags from the attributed subgraph, for example
   `added_dependency`, `cross_module_call`, `global_state` and `mutual_import`, weighted by
   positive attribution.
2. **Retrieval:** 50 design-principle cards (`docs/principles/`: SOLID, package principles,
   coupling smells, refactorings and Python-specific advice) are retrieved by those tags, not by the
   question text. A BM25 retriever on the PR title and diff is the "conventional RAG" comparison.
3. **Generation:** Groq `openai/gpt-oss-120b` returns strict JSON: verdict, explanation, cited
   edges, principle ids and a suggested refactoring.
4. **Grounding:** an answer is rejected, with one repair attempt, if it cites an edge or principle
   that was not supplied, or a number not in the input.

```powershell
python scripts/rag_v5_explain.py --attribution data/xai/v5/OWNER__REPO__N.json --out data/rag_v5/explanations/OWNER__REPO__N.json --mode signature
python scripts/rag_v5_evaluate.py --references docs/eval_v5/references.json   # BERTScore, ROUGE, P@3, grounding
python scripts/rag_v5_google_form.py build                                                             # blind A/B/C survey + private key
python scripts/rag_v5_survey.py --responses data/rag_v5/survey_long.csv --key data/rag_v5/survey_key.json
```

`--mode` is `signature` (ours), `text` (BM25) or `none`. The evaluation uses 40 held-out PRs with
hand-written reference explanations. The survey's private key (`data/rag_v5/survey_key.json`)
must match the published form. Method and results: `docs/report_v5/rag_section.md`.

## Graph validation and tool baselines

**Is the graph correct?** (`scripts/validate_graph_v5.py`, write-up in
`docs/validation_v5/graph_validation.md`):

| Check | Precision | Recall | F1 |
|---|---:|---:|---:|
| CALLS vs the PyCG micro-benchmark, ours (119 programs) | 97.2 | 43.6 | 60.2 |
| CALLS, PyCG itself on the same benchmark | 95.9 | 87.7 | 91.6 |
| IMPORTS vs grimp, 10 repositories | 97.7 | 100.0 | 98.8 |
| IMPORTS vs grimp, modules both tools scan | 100.0 | 100.0 | 100.0 |
| Gold set: CALLS / INHERITS / ACCESSES_GLOBAL | 97.9 / 100 / 80.0 | 88.7 / 76.3 / 50.0 | 93.1 / 86.6 / 61.5 |

The graph's edges are precise. Its recall is limited where values flow through assignments,
containers or returns. The gold set is small (6 files, 99 relations), its labels were AI-drafted,
and an independent second labeller is pending. Extraction bugs found are listed with minimal
examples in `docs/validation_v5/bugs_found.md`.

```powershell
python scripts/validate_graph_v5.py --pycg-dir <PyCG clone> --repos-dir <checkouts> --pycg-python <Python 3.10 with PyCG> --out data/validation_v5/
```

**Established tools as baselines** (`docs/validation_v5/tool_baselines.md`). Every tool reads the
touched files at the commit before the PR and at the merge, so it uses no information from after
the merge:

* radon, pylint and a CodeScene-style hotspot (our re-implementation of the published method, not
  CodeScene): `scripts/run_tool_metrics_v5.py` (parallel) or `scripts/tool_metrics_v5.py` →
  `data/tool_metrics_v5.jsonl`, 6,141 PRs;
* SonarQube Community 26.10, in Docker (`docker/sonarqube/`): `scripts/sonar_v5.py` scans
  250 PRs at a time → `data/sonar_v5.jsonl`, 6,140 PRs.

These tools score files one at a time and cannot see coupling across modules, which is what the
label measures.

## Tests

```powershell
python -m pytest -q
```

`pytest.ini` limits collection to `tests/`, so the cloned projects' own tests never run. Tests need
no network, Docker or API keys.

## Repository layout

```text
src/analysis/        AST parser, dependency graph, node features (points 2-4)
src/ml/              HeteroData schema, GNN, training data, shortcut baselines, split planning
src/dataset/         snapshots, future-coupling labels, history features, structural metrics
src/semantic/        diff encoder (CodeBERT / CodeReviewer)
src/fusion/          fusion data alignment, model and evaluation
src/xai/             XAI layers A-C (v3/v4) and v5 edge attribution
src/rag/             the chatbot: knowledge cards, retrieval, grounded answers
src/rag_v5/          XAI-grounded RAG: signature, retrieval, generation, grounding check
src/validation_v5/   graph validation (PyCG, grimp, gold set), radon/pylint/hotspot, SonarQube
src/live_pr.py       live GitHub PR preparation and scoring
src/github/, src/scraper/, src/filtering/   PR metadata collection (v3/v4)
api/                 FastAPI back end (main.py, views.py, v5_attribution.py)
web/                 React front end
scripts/             one command per workflow step
docs/knowledge/      method notes the chatbot cites
docs/principles/     the 50 design-principle cards
docs/report_v5/      maths, RAG report section
docs/validation_v5/  graph validation, tool baselines, bugs found
docs/eval_v5/        reference answers, evidence sheets, survey material
config/              settings, repository lists, data splits, chatbot settings
notebooks/           Kaggle notebooks for embedding and training
tests/               project tests and fixtures
```

Tokens, clones, datasets, checkpoints, embeddings and generated results are kept out of Git and
shared separately.

## Limitations

* **Static analysis** cannot see dynamic imports, reflection, monkey-patching or calls through
  values in containers. This mostly means missing edges, so the coupling measures are conservative.
* **The label is an outcome proxy:** other PRs in the six months also change the touched modules. It
  is not a causal claim.
* **Attributions describe the model**, not the real cause of later coupling growth.
* **Scores are uncalibrated.** Compare PRs by score and use the threshold for the decision.
* **The gold set is small and AI-drafted.** Survey responses are still being collected.

## Earlier versions (v3 and v4)

* **v3** labelled a PR risky when a human-reviewed architectural refactor touched the same files
  within six months, and split PRs by merge time. Its GNN pooled the whole repository and the
  touched nodes.
* **v4** kept the reviewed labels, held out whole repositories (Flask and Jinja for training, Click
  for validation, Werkzeug for testing), pooled only touched files and their neighbours, and added
  CodeReviewer, fusion, XAI layers A–C, the chatbot and the web app. `scripts/run_all.py
  --manifest artifacts/gnn_embeddings_v4.json` rebuilds that chain.

The v3/v4 data collection (GraphQL scraping with coverage files, event reviews,
`label_future_refactors.py`, `build_future_pr_dataset.py`, `train_gnn.py`, history audits) is still
in the repository. The previous README documents it in full: `git show d06a926:README.md`.
