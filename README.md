# Python PR Architecture Dataset Pipeline

This project implements flow-graph points **1–4**:

```text
1. Clone and store Python repositories
2. Parse Python source with AST
3. Build a static dependency graph
4. Create explainable node features
```

It also retains the earlier repository selection, GitHub merged-PR metadata collection, and deterministic PR filtering workflow. It does **not** implement graph-to-PyTorch conversion, GNNs, CodeBERT, graph comparison, risk prediction, XAI, RAG, or LLM remediation.

## Architecture

```text
repositories.json → GitHub GraphQL → raw PR JSONL → filtering
                                                  ↓
config/repositories.json → Git clone → AST facts → dependency graph → node features
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

By default it skips test directories and common virtual environment/build/cache directories. This is configurable under `static_analysis` in [config/settings.json](config/settings.json).

### Dependency graph (point 3)

`dependency_graph.json` contains typed nodes and these directed edges:

- `CONTAINS`: module → class/function and class → method;
- `IMPORTS`: a symbol scope → imported local/external module;
- `CALLS`: a symbol scope → locally resolved or external callable.

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

## Run and test points 1–4

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

Static analysis is syntactic and static: it cannot fully resolve dynamic imports, reflection, monkey patching, or all attribute calls. It deliberately does not execute target code. The graph and features are point-4 artifacts, not a risk classifier or a trained ML dataset yet.
