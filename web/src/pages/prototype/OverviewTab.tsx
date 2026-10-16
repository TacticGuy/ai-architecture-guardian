import { useEffect, useState } from "react";

import { DataTable, Legend, Notice, Panel, Stat } from "@/components/kit";
import { api, type Overview } from "@/lib/api";

export default function OverviewTab({ version }: { version: string }) {
  const [data, setData] = useState<Overview>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    setData(undefined);
    setError(undefined);
    api.overview(version).then(setData).catch((exc: Error) => setError(exc.message));
  }, [version]);

  if (error) return <Notice kind="error">{error}</Notice>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading results</p>;

  const head = data.headline;
  const gap = (mine?: number, base?: number) =>
    mine !== undefined && base !== undefined && Math.abs(mine - base) >= 0.0005
      ? `${mine - base > 0 ? "+" : ""}${(mine - base).toFixed(3)} vs always-risky` : undefined;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="PRs in the dataset" value={data.dataset_count} />
        <Stat label="Test PRs" value={head.test_prs ?? "-"} />
        {head.fusion_f1 !== undefined && (
          <>
            <Stat label="Fusion test F1" value={head.fusion_f1.toFixed(3)} hint={gap(head.fusion_f1, head.baseline_f1)} />
            <Stat label="Fusion test PR-AUC" value={head.fusion_ap!.toFixed(3)} hint={gap(head.fusion_ap, head.baseline_ap)} />
          </>
        )}
      </div>
      {head.baseline_f1 !== undefined && (
        <p className="text-sm text-muted-foreground">
          Always-risky baseline (calls every PR risky): F1 {head.baseline_f1.toFixed(3)}, PR-AUC {head.baseline_ap!.toFixed(3)}.
        </p>
      )}
      {data.warnings.map((warning) => <Notice key={warning} kind="warn">{warning}</Notice>)}

      <Panel
        title="Model results on the test split"
        caption="Threshold picked on validation (best F1). Ranges are bootstrap 95% ranges: with few test PRs, read the ranges, not single numbers."
      >
        <DataTable rows={data.results} />
      </Panel>

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Panel title="Risk score of every test PR" caption={`Fusion risk score. The vertical line is the threshold, ${data.threshold.toFixed(3)}.`}>
          <Legend items={[{ label: "safe (0)", className: "bg-safe" }, { label: "risky (1)", className: "bg-risky" }]} />
          <ul className="space-y-2">
            {data.scores.map((row) => (
              <li key={row.sample_id} className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-3" title={`${row.sample_id}: predicted ${row.Prediction}, correct: ${row.Correct}`}>
                <span className="text-sm tabular-nums">{row.PR}</span>
                <div className="relative h-3.5 rounded-sm bg-muted">
                  <div
                    className={`absolute inset-y-0 left-0 rounded-sm transition-[width] duration-700 ${row["True label"].startsWith("risky") ? "bg-risky" : "bg-safe"}`}
                    style={{ width: `${Math.min(row["Risk score"], 1) * 100}%` }}
                  />
                  <div className="absolute inset-y-[-3px] w-0.5 bg-foreground/70" style={{ left: `${data.threshold * 100}%` }} />
                </div>
                <span className="text-right text-xs tabular-nums text-muted-foreground">{row["Risk score"].toFixed(3)}</span>
              </li>
            ))}
          </ul>
          {data.scores.length === 0 && <p className="text-sm text-muted-foreground">No test predictions found.</p>}
        </Panel>

        <Panel title="Dataset">
          <DataTable rows={data.splits} />
          {data.purged.length > 0 && (
            <p className="mt-4 text-sm leading-6 text-muted-foreground">
              {data.purged.length} PRs were purged because their six-month outcome window crosses a split cutoff:{" "}
              {data.purged.map((pr) => `#${pr}`).join(", ")}
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}
