# Reference-answer guidelines (v5)

Write one answer per real, test-split PR after reading its attribution file and
the actual GitHub diff. The reference must state whether the model predicts
degradation, name the two or three strongest *real* dependency edges, connect
them to a relevant design principle, and propose the smallest concrete change
that could reduce the risk. Use short sentences and name the file that would
change. A safe PR may need only a monitoring or testing recommendation; do not
force a refactoring.

Do not infer the true future outcome from the model prediction. Do not invent
missing edges, metrics, principles, or code behavior. Avoid claims that a risk
score is a calibrated probability. An attribution is a model explanation, not
proof that the code is defective. Note uncertainty when evidence is weak or
conflicting. Keep reference writers blind to which retrieval method produced
each generated answer.

Selection: from real files with `split=test`, use seed 2026 to sample up to
20 predicted-degrading and 20 predicted-safe PRs. Record any shortfall. Human
judges should mark relevant principle-card IDs before seeing system outputs.
The JSON record for each selected PR has `sample_id`, `attribution_path`,
`reference_explanation`, `reference_fix`, and `relevant_principles` fields.
