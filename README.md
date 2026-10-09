# Python PR Architecture Dataset Pipeline

This project implements flow-graph points **1–5**:

```text
1. Clone and store Python repositories
2. Parse Python source with AST
3. Build a static dependency graph
4. Create explainable node features
5. Convert each graph to PyTorch Geometric HeteroData
```

It also retains the earlier repository selection, GitHub merged-PR metadata collection, and deterministic PR filtering workflow. It does **not** implement GNNs, CodeBERT, graph comparison, risk prediction, XAI, RAG, or LLM remediation.

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
python -m pytest -v
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

Static analysis is syntactic and static: it cannot fully resolve dynamic imports, reflection, monkey patching, or all attribute calls. It deliberately does not execute target code. The point-5 graphs describe one version of each repository's code; they are not yet a labelled, per-pull-request training dataset.
