# Python PR Architecture Dataset Pipeline

This implementation covers repository selection, PR metadata collection, and PR filtering only. It does not clone repositories or generate code snapshots.

It builds a reproducible research dataset:

```text
configured Python repositories → GitHub GraphQL metadata → raw JSONL → deterministic filters → filtered JSONL
```

It intentionally stops before Stage 4: no repository cloning, source-code download, before/after snapshots, AST parsing, or dependency-graph generation is implemented.

## Architecture

- `config/repositories.json` is the sole repository list (20 mature Python projects).
- `GitHubClient` sends direct GraphQL POST requests, detects HTTP/GraphQL failures, retries temporary failures, and tracks rate limits.
- `PullRequestScraper` streams merged PR pages to raw JSONL and atomically saves a cursor checkpoint after every page.
- The filter applies `changed_files >= 3` before deterministic, case-insensitive substring matching in title, body, and commit messages.
- Statistics recompute filtering decisions from raw data for auditability.

Commit metadata is requested with `max_commits_per_pr` (100 by default). A PR beyond that cap is marked `commit_metadata_complete: false`.

## Layout

```text
config/                 repository and pipeline configuration
src/github/             GraphQL client, queries, rate-limit handling
src/scraper/            cursor checkpoint and streaming scraper
src/filtering/          impact and keyword filters
src/storage/            JSONL streaming and duplicate handling
scripts/                runnable commands
tests/                  offline pytest suite
data/raw/               raw_prs.jsonl and scrape_checkpoint.json (runtime)
data/filtered/          filtered_prs.jsonl (runtime)
data/statistics/        filtering_statistics.json (runtime)
logs/pipeline.log       diagnostics (runtime)
```

## Requirements and setup

Use Python 3.10+ (Python 3.11 is preferred) and a GitHub Personal Access Token. Create a fine-grained token with read access to public repository metadata, or a classic token for public data.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `GITHUB_TOKEN=...`. The token is never printed and `.env` is ignored by Git. See <https://github.com/settings/tokens>.

## First-run procedure

Run these commands from the project root:

```powershell
python scripts/test_github_connection.py
pytest -v
python scripts/scrape_prs.py --repo django/django --max-prs 10
Get-Content data/raw/raw_prs.jsonl
python scripts/filter_prs.py
Get-Content data/filtered/filtered_prs.jsonl
python scripts/generate_statistics.py
python scripts/validate_dataset.py
```

`--max-prs 10` asks GraphQL for 10 records rather than fetching 100 and discarding part of a page. Repeated collection is safe: raw JSONL has stable `repo#number` duplicate prevention. Test pagination with:

```powershell
python scripts/scrape_prs.py --repo django/django --max-prs 100
```

## Full collection and resume

After the small run succeeds:

```powershell
python scripts/scrape_prs.py --all --resume
python scripts/scrape_prs.py --all --resume --target-prs 50000
```

The target is a cap, not a promise. The scraper sizes requests to remaining capacity and ends cleanly after a fully processed response. It does not force the final count into 12,000–15,000; actual output is reported.

`--resume` continues from `data/raw/scrape_checkpoint.json` and skips completed repositories. `--fresh` explicitly resets only the cursor checkpoint; it **does not delete raw data** and existing PR IDs are skipped. Archive/delete data yourself only when intentionally starting a separate collection.

Useful variants:

```powershell
python scripts/scrape_prs.py --all --max-prs-per-repo 100
python scripts/scrape_prs.py --repo django/django --max-prs 10 --fresh
python scripts/scrape_prs.py --help
python scripts/filter_prs.py --help
python scripts/generate_statistics.py --help
python scripts/validate_dataset.py --help
```

## Data formats and filtering

Raw `data/raw/raw_prs.jsonl` has one object per PR, including `pr_id`, repository identity, title/body, timestamps, `changed_files`, `commit_messages`, `commit_metadata_complete`, and `scraped_at`. Null bodies become `""`; deleted authors become `null`.

Filtered `data/filtered/filtered_prs.jsonl` has only accepted records plus:

```json
{"impact_filter": true, "semantic_filter": true, "matched_keywords": ["refactor"], "filter_status": "accepted"}
```

Keywords are configured in `config/settings.json`. Matching is deterministic, case-insensitive substring matching in configured-list order. No LLMs, embeddings, fuzzy matching, or random sampling are used.
Every raw PR also receives a traceable decision in `data/statistics/filtering_decisions.jsonl`: `accepted`, `rejected_impact`, or `rejected_semantic`, with the applicable filter fields and keyword matches.

## Rate limits, tests, and validation

Successful requests log cost, remaining quota, and reset time to `logs/pipeline.log`. Configuration controls the warning threshold, wait policy, retries, timeouts, page sizes, commit cap, impact threshold, and keywords.

Temporary 502/503/504/network failures retry with exponential backoff. Authentication and GraphQL errors fail clearly without blind retries. One failed repository does not stop `--all`; failures are listed in the summary.

- `test_github_connection.py` verifies credentials, API reachability, configured repository access, and rate-limit fields.
- `pytest -v` uses mocked HTTP/GraphQL responses only—no test contacts GitHub.
- `generate_statistics.py` writes repository/configuration metadata, per-repo counts, changed-file mean/median, filter stage counts, and keyword frequencies.
- `validate_dataset.py` validates JSONL, identifiers, duplicates, raw provenance, filters, accepted status, and keyword matches.

## Troubleshooting

- **GITHUB_TOKEN is not set**: copy `.env.example` to `.env`, set the token, and run from project root.
- **401/Bad credentials**: create/replace the token; omit quote marks.
- **Repository not found**: verify owner/name and token permissions.
- **Rate limited**: wait for reset or reduce the requested PR limit.
- **Interrupted scrape**: rerun with `--resume`.
- **Corrupt checkpoint**: the scraper moves it to a `.corrupt` file and reports it.
- **Unexpected accepted count**: inspect statistics; never trim records merely to hit a target.

## Limits

This is a metadata collection and deterministic filtering prototype. It does not retrieve source, clone repositories, generate snapshots, parse ASTs, or build dependency graphs.
