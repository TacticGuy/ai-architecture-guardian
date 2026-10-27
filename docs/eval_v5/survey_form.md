# Blind explanation survey - form shell

This is a **shell only**, not a sent survey. After real v5 attributions have
been evaluated, run `python scripts/rag_v5_survey.py` to replace this file with
12 PRs, three blinded answers per PR, and the copy-ready question text. Keep
`data/rag_v5/survey_key.json` private from respondents.

Opening questions:

1. How many years have you written code? (number)
2. Which best describes you? Student / professional developer / other

For each PR, show the evidence summary and explanations A, B, and C. For each
explanation, ask four 1-to-5 ratings: correctness, usefulness for a code
reviewer, actionability of the proposed fix, and clarity. Use one response per
person. Do not show the method names or the order key.

No PR explanations or responses have been invented here.
