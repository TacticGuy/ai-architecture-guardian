# Shynaa v5 RAG handover

## Implemented

- `src/rag_v5/signature.py`: deterministic evidence tags and normalized weights.
- `src/rag_v5/retrieval.py`: principle-card parser, signature retrieval, and text-BM25 baseline.
- `src/rag_v5/generate.py`: strict grounded JSON generation with one repair attempt.
- `src/rag_v5/grounding.py`: unsupported edge, principle, and number checks.
- `scripts/rag_v5_explain.py`: attribution-to-explanation CLI.
- `scripts/rag_v5_evaluate.py`: fixed-seed selection, evidence sheets, three-mode evaluation,
  bootstrap intervals, Wilcoxon tests, results table, and chart.
- `scripts/rag_v5_survey.py`: blinded A/B/C form text, private key, and real-response analysis.
- 50 sourced design cards in `docs/principles/`.
- The explanation prompt accepts the four-part Layer A split (`base`, `structure_gnn`,
  `history`, and `diff`) and includes the new `history_features` evidence object.
- Synthetic high-risk and safe fixtures, clearly marked as test-only.
- Mathematical formulations, proofs with necessary conditions, report draft, guidelines,
  reference template, and survey shell.

## Setup and commands

Run from the repository root with Python 3.10 or newer:

```powershell
python -m pip install -r requirements.txt -r requirements-rag-v5.txt
python -m pytest tests/test_rag_v5_core.py tests/test_rag_v5_metric_properties.py tests/test_rag_v5_tools.py -q
```

Generate one real explanation after setting `GROQ_API_KEY` in `.env`:

```powershell
python scripts/rag_v5_explain.py --attribution data/xai_v5/OWNER__REPO__NUMBER.json `
  --out data/rag_v5/explanations/OWNER__REPO__NUMBER.json --mode signature
```

Use `--mode text` for the title-and-diff BM25 baseline and `--mode none` for no retrieval.
The primary Groq model is `openai/gpt-oss-120b`. The implementation uses
`openai/gpt-oss-20b` as fallback because Groq deprecated `llama-3.3-70b-versatile` for
free/developer plans in August 2026.

When real attribution files exist:

```powershell
python scripts/rag_v5_evaluate.py --prepare-sheets
```

This selects up to 20 predicted-degrading and 20 predicted-safe test PRs with seed 2026,
writes readable sheets under `docs/eval_v5/sheets/`, and creates
`docs/eval_v5/references_draft.json`. Complete every reference and relevant-principle list
by hand after checking the real GitHub diff. Then replace/point `--references` at that file:

```powershell
python scripts/rag_v5_evaluate.py --references docs/eval_v5/references_draft.json
python scripts/rag_v5_survey.py
```

Copy `docs/eval_v5/survey_form.md` into Google Forms and keep
`data/rag_v5/survey_key.json` private. After exporting responses in the documented CSV shape:

```powershell
python scripts/rag_v5_survey.py --responses path/to/real_responses.csv
```

## Still blocked on external inputs

1. No real `data/xai_v5/*.json` attribution files were present locally or on the fetched
   `origin/update/dashboard` branch on 27 October 2026.
2. The 40 reference explanations and relevant-principle labels must be written by humans
   from those files and their real GitHub diffs.
3. Live generation requires the user's Groq key. No key was created or committed.
4. The survey must be sent to real respondents; their answers must not be synthesized.
5. `data/rag_v5/` should be added to `.gitignore` by the integration owner because this
   work package forbids editing the existing `.gitignore`.

## Verification and known issues

- All 26 focused v5 tests pass without network calls.
- The 31 related existing future-coupling, structural-metric, global-edge, and v5 XAI tests
  also pass. The XAI tests required a temporary directory outside OneDrive because local Git
  references were intermittently locked inside the synchronized folder.
- Python compilation succeeds for the package and all three scripts.
- Evaluation packages install and import in the existing project environment.
- A full repository `pytest -q` attempt stalled in the command runner without output and was
  interrupted after the Python process disappeared. This is not reported as a passing full suite.
- BERTScore will download the `roberta-large` model on the first real evaluation run, so that
  run needs network access and disk space.
- The evaluation script rejects blank references and synthetic fixtures, preventing accidental
  publication of fabricated results.
