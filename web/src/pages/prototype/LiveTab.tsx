import { useState, type FormEvent } from "react";

import { DivergingBars, Legend, Notice, Panel, Stat } from "@/components/kit";
import { LoadingButton } from "@/components/ui/loading-button";
import { api, type LiveReport } from "@/lib/api";
import { HunkList } from "@/pages/prototype/ExplorerTab";

export default function LiveTab({ version }: { version: string }) {
  const [url, setUrl] = useState("");
  const [hunks, setHunks] = useState(3);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<LiveReport>();
  const [error, setError] = useState<string>();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!url.trim() || loading) return;
    setLoading(true);
    setError(undefined);
    try {
      setReport(await api.live(url.trim(), hunks, version));
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Panel
        title="Analyse an open GitHub pull request"
        caption="Uses the PR's base graph and current diff. The result has no historical true label and is not added to the training dataset. First analysis may take a few minutes."
      >
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm text-muted-foreground">
            Public GitHub PR URL
            <input
              type="url" value={url} onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/owner/repo/pull/123"
              className="mt-1.5 h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground/70"
            />
          </label>
          <label className="block max-w-xs text-sm text-muted-foreground">
            Diff hunks to explain: <span className="tabular-nums text-foreground">{hunks}</span>
            <input type="range" min={0} max={5} value={hunks} onChange={(event) => setHunks(Number(event.target.value))} className="mt-2 block w-full accent-foreground" />
          </label>
          <LoadingButton type="submit" loading={loading} disabled={!url.trim()}>
            {loading ? "Analysing" : "Analyse live PR"}
          </LoadingButton>
          {loading && <p className="text-sm text-muted-foreground">Fetching the PR, building its base graph, and running the models.</p>}
        </form>
      </Panel>

      {error && <Notice kind="error">{error}</Notice>}

      {report && (
        <div className="space-y-6">
          <p className="text-sm font-medium">
            <a href={report.url} target="_blank" rel="noreferrer" className="underline underline-offset-4">{report.sample_id}</a>
            {" "}- {report.title}
          </p>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Fusion risk" value={`${report.risk_percent.toFixed(1)}%`} />
            <Stat label="Decision" value={report.classification.replace(/_/g, " ")} />
            <Stat label="GNN score" value={report.gnn_probability.toFixed(3)} />
            <Stat label="Threshold" value={report.threshold.toFixed(3)} />
          </div>
          <Notice kind="warn">{report.warning}</Notice>
          <Panel title="Structure vs diff">
            <Legend items={[{ label: "pushes risk down", className: "bg-safe" }, { label: "pushes risk up", className: "bg-risky" }]} />
            <DivergingBars rows={report.layer_a.map((row) => ({ label: row.Part, value: row.Logit, tone: row.Direction.includes("up") ? "risky" : "safe" }))} />
          </Panel>
          {report.hunks.length > 0 && (
            <Panel title="Influential changed hunks"><HunkList hunks={report.hunks} /></Panel>
          )}
          <p className="break-all text-xs text-muted-foreground">Saved locally: {report.saved_path}</p>
        </div>
      )}
    </div>
  );
}
