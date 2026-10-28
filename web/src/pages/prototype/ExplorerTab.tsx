import { useEffect, useMemo, useState } from "react";

import { DataTable, DivergingBars, Legend, Notice, Panel, Stat } from "@/components/kit";
import { api, type HunkRow, type PrDetail, type PrMeta } from "@/lib/api";

export function HunkList({ hunks }: { hunks: HunkRow[] }) {
  if (!hunks.length) return <p className="text-sm text-muted-foreground">No hunks in analysed files.</p>;
  return (
    <div className="space-y-4">
      <DataTable
        rows={hunks.map(({ snippet: _snippet, ...row }) => row)}
      />
      {hunks.slice(0, 3).map((hunk, index) => (
        <details key={index} className="group rounded-xl border border-border">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium">
            {hunk.File} lines {hunk.Lines} (effect {hunk["Effect on risk"] > 0 ? "+" : ""}{hunk["Effect on risk"].toFixed(4)})
          </summary>
          <pre className="overflow-x-auto border-t border-border bg-muted p-4 font-mono text-xs leading-5">
            {hunk.snippet || "(no changed lines)"}
          </pre>
        </details>
      ))}
    </div>
  );
}

export default function ExplorerTab({ version }: { version: string }) {
  const [prs, setPrs] = useState<PrMeta[]>([]);
  const [onlyExplained, setOnlyExplained] = useState(true);
  const [selected, setSelected] = useState<string>();
  const [detail, setDetail] = useState<PrDetail>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    setError(undefined);
    api.prs(version).then((result) => setPrs(result.prs)).catch((exc: Error) => setError(exc.message));
  }, [version]);

  const choices = useMemo(() => prs.filter((pr) => pr.explained || !onlyExplained), [prs, onlyExplained]);
  const current = choices.find((pr) => pr.sample_id === selected) ?? choices[0];

  useEffect(() => {
    if (!current) { setDetail(undefined); return; }
    let cancelled = false;
    setDetail(undefined);
    api.prDetail(current.sample_id, version)
      .then((result) => { if (!cancelled) setDetail(result); })
      .catch((exc: Error) => { if (!cancelled) setError(exc.message); });
    return () => { cancelled = true; };
  }, [current?.sample_id, version]);

  if (error) return <Notice kind="error">{error}</Notice>;
  const explanation = detail?.explanation;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm text-muted-foreground sm:max-w-xl">
          Pull request
          <select
            value={current?.sample_id ?? ""} onChange={(event) => setSelected(event.target.value)}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
          >
            {choices.map((pr) => <option key={pr.sample_id} value={pr.sample_id}>{pr.label_text}</option>)}
          </select>
        </label>
        <label className="mt-6 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyExplained} onChange={(event) => setOnlyExplained(event.target.checked)} className="size-4 accent-foreground" />
          Only PRs with explanations
        </label>
      </div>

      {!current && <Notice>No explained PRs yet. Run: python scripts/explain_prs.py --manifest artifacts/gnn_embeddings_&lt;v&gt;.json</Notice>}
      {current && !detail && <p className="text-sm text-muted-foreground">Loading PR</p>}

      {detail && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Fusion risk score" value={detail.probability.toFixed(3)} />
            <Stat label="Threshold" value={detail.threshold.toFixed(3)} />
            <Stat label="True label" value={detail.label ? "risky (1)" : "safe (0)"} />
            <Stat label="Prediction" value={detail.correct ? "correct" : "WRONG"} tone={detail.correct ? "good" : "bad"} />
          </div>
          <details className="rounded-xl border border-border">
            <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium">Everything the chatbot knows about this PR</summary>
            <pre className="overflow-x-auto whitespace-pre-wrap border-t border-border p-4 font-mono text-xs leading-5">{detail.card}</pre>
          </details>

          {!explanation && detail.has_attribution_v5 && (
            <Notice>This PR's v5 edge-level explanation is in the Attribution tab.</Notice>
          )}
          {!explanation && !detail.has_attribution_v5 && (
            <Notice>This PR has no XAI explanation yet. Run explain_prs.py with --split all to add it.</Notice>
          )}
          {explanation && (
            <>
              <Panel title="Layer A: structure vs diff" caption="How much each input moved the score (logit units). They add up: base + structure + diff.">
                <Legend items={[{ label: "pushes risk down", className: "bg-safe" }, { label: "pushes risk up", className: "bg-risky" }]} />
                <DivergingBars rows={explanation.layer_a.map((row) => ({ label: row.Part, value: row.Logit, tone: row.Direction.includes("up") ? "risky" : "safe" }))} />
              </Panel>
              <Panel title="Layer B: which diff hunks mattered" caption="Each hunk was hidden and the PR re-scored. Positive means this hunk pushed the risk up.">
                <HunkList hunks={explanation.layer_b} />
              </Panel>
              <Panel
                title="Layer C: which code files mattered"
                caption={explanation.layer_c
                  ? `Integrated Gradients on the GNN. Touched files total ${explanation.layer_c.touched_total.toFixed(2)}, untouched files total ${explanation.layer_c.untouched_total.toFixed(2)}.`
                  : "Layer C was skipped for this PR (run explain_prs.py without --no-graph)."}
              >
                {explanation.layer_c && (
                  <>
                    <Legend items={[{ label: "touched by PR", className: "bg-safe" }, { label: "not touched", className: "bg-risky" }]} />
                    <DivergingBars
                      rows={explanation.layer_c.files.map((row) => ({
                        label: row.File, value: row.Effect, tone: row["Touched by PR"] === "touched" ? "safe" : "risky",
                        detail: `${row.Nodes} nodes`,
                      }))}
                    />
                  </>
                )}
              </Panel>
              {explanation.note && <p className="text-sm text-muted-foreground">{explanation.note}</p>}
            </>
          )}
        </>
      )}
    </div>
  );
}
