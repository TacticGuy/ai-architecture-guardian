import { ExternalLink, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";

import { DivergingBars, Notice, Panel } from "@/components/kit";
import { Markdown } from "@/components/Markdown";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ data (brief §2.3 and §2.4) */

interface AttributionSummary {
  sample_id: string; repo: string; title: string; risk_score: number; threshold: number;
  predicted_degrading: boolean; label: number | null; split: string; has_explanation: boolean;
}
interface Edge {
  // The module is null for external_callable / external_module nodes (code outside the project).
  source: string; source_type: string; source_module: string | null; relation: string; target: string;
  target_type: string; target_module: string | null; attribution: number; added_in_pr: boolean;
  touched_source: boolean; touched_target: boolean;
}
interface ModuleEvidence { ca_before: number; ce_before: number; ca_after: number; ce_after: number; in_import_cycle: boolean }
interface Hunk { file: string; lines: [number, number]; effect: number; snippet: string[] }
interface Explanation {
  verdict?: string; explanation?: string; evidence?: { edge: string; why: string }[]; principles?: string[];
  suggestion?: { refactoring?: string | null; files?: string[]; steps?: string[]; code_sketch?: string | null };
  confidence_note?: string;
  // Written by src/rag_v5 (explain_pr): which cards were retrieved and why, and the grounding check.
  mode?: string; status?: string; retrieved_cards?: { id: string; reason: string }[]; grounding_violations?: string[];
}
interface Attribution extends AttributionSummary {
  merged_at: string | null; label_reason: string | null;
  layer_a: { base: number; structure_gnn: number; diff: number; history?: number };  // history: v5.1 only
  changed_files: string[]; touched_modules: string[]; top_edges: Edge[];
  module_evidence: Record<string, ModuleEvidence>; pr_creates_cycle: boolean; new_cycle_modules: string[];
  structural_delta: Record<string, number>; top_hunks: Hunk[]; unfaithfulness: number; explainer: string;
  explanation: Explanation | null;
}

async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    throw new Error("Cannot reach the API. Start it with: uvicorn api.main:app --port 8000");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const detailPath = (sampleId: string) => {
  const match = /^([^/]+)\/([^#]+)#(\d+)$/.exec(sampleId);
  return match ? `/api/v5/attributions/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}/${match[3]}` : null;
};
const prUrl = (sampleId: string) => {
  const match = /^([^/]+)\/([^#]+)#(\d+)$/.exec(sampleId);
  return match ? `https://github.com/${match[1]}/${match[2]}/pull/${match[3]}` : undefined;
};
const signed = (value: number, digits = 2) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
/** Two decimals, but small non-zero values keep two significant digits (0.00048, not 0.00). */
const small = (value: number) => (value === 0 ? "0" : Math.abs(value) < 0.01 ? value.toPrecision(2) : value.toFixed(2));

/* ------------------------------------------------------------------ page */

export default function AttributionTab() {
  const [rows, setRows] = useState<AttributionSummary[]>();
  const [listError, setListError] = useState<string>();
  const [query, setQuery] = useState("");
  const [split, setSplit] = useState("all");
  const [verdict, setVerdict] = useState<"all" | "degrading" | "safe">("all");
  const [selected, setSelected] = useState<string>();
  const [detail, setDetail] = useState<Attribution>();
  const [detailError, setDetailError] = useState<string>();

  useEffect(() => {
    getJson<AttributionSummary[]>("/api/v5/attributions").then(setRows).catch((exc: Error) => setListError(exc.message));
  }, []);

  const splits = useMemo(() => [...new Set((rows ?? []).map((row) => row.split))].sort(), [rows]);
  const visible = useMemo(() => (rows ?? []).filter((row) =>
    (split === "all" || row.split === split)
    && (verdict === "all" || row.predicted_degrading === (verdict === "degrading"))
    && (!query.trim() || `${row.sample_id} ${row.title}`.toLowerCase().includes(query.trim().toLowerCase())),
  ), [rows, split, verdict, query]);
  const current = visible.find((row) => row.sample_id === selected) ?? visible[0];

  useEffect(() => {
    const path = current && detailPath(current.sample_id);
    setDetail(undefined);
    setDetailError(undefined);
    if (!path) return;
    let cancelled = false;
    getJson<Attribution>(path)
      .then((result) => { if (!cancelled) setDetail(result); })
      .catch((exc: Error) => { if (!cancelled) setDetailError(exc.message); });
    return () => { cancelled = true; };
  }, [current?.sample_id]);

  if (listError) return <Notice kind="error">{listError}</Notice>;
  if (!rows) return <p className="animate-pulse text-sm text-muted-foreground">Loading attributions</p>;
  if (!rows.length) {
    return (
      <Notice>
        No attribution files yet. They are read from <code className="font-mono">data/xai/v5/</code> (one{" "}
        <code className="font-mono">&lt;owner&gt;__&lt;repo&gt;__&lt;number&gt;.json</code> per PR).
      </Notice>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[19rem_minmax(0,1fr)]">
      <aside className="min-w-0 space-y-3">
        <label className="relative block">
          <span className="sr-only">Search PRs</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repo, number or title"
            className="h-10 w-full rounded-lg border border-input bg-background pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <select aria-label="Split" value={split} onChange={(event) => setSplit(event.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm">
            <option value="all">All splits</option>
            {splits.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <select aria-label="Prediction" value={verdict} onChange={(event) => setVerdict(event.target.value as typeof verdict)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm">
            <option value="all">All predictions</option>
            <option value="degrading">Degrading</option>
            <option value="safe">Safe</option>
          </select>
        </div>
        <p className="text-xs text-muted-foreground">{visible.length} of {rows.length} PRs</p>
        <ul className="max-h-[22rem] space-y-1.5 overflow-y-auto pr-1 lg:max-h-[46rem]" aria-label="Pull requests">
          {visible.map((row) => (
            <li key={row.sample_id}>
              <button
                type="button" onClick={() => setSelected(row.sample_id)} aria-current={row.sample_id === current?.sample_id}
                className={cn(
                  "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
                  row.sample_id === current?.sample_id ? "border-foreground/40 bg-muted" : "border-border hover:bg-muted/60",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs">{row.sample_id}</span>
                  <span className={cn("shrink-0 text-xs font-semibold tabular-nums", row.predicted_degrading ? "text-risky" : "text-safe")}>
                    {(row.risk_score * 100).toFixed(0)}%
                  </span>
                </span>
                <span className="mt-1 line-clamp-2 block text-sm leading-5">{row.title}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {row.split}{row.has_explanation ? " · explained" : ""}
                </span>
              </button>
            </li>
          ))}
          {!visible.length && <li className="text-sm text-muted-foreground">No PR matches these filters.</li>}
        </ul>
      </aside>

      <div className="min-w-0 space-y-6">
        {detailError && <Notice kind="error">{detailError}</Notice>}
        {!detail && !detailError && current && <p className="animate-pulse text-sm text-muted-foreground">Loading {current.sample_id}</p>}
        {detail && <Detail data={detail} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ detail sections */

function Detail({ data }: { data: Attribution }) {
  const url = prUrl(data.sample_id);
  return (
    <>
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs text-muted-foreground">{data.sample_id} · {data.split}</p>
            <h2 className="mt-1 text-lg font-semibold leading-7 tracking-tight">{data.title}</h2>
          </div>
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-input px-3 py-1.5 text-sm transition-colors hover:bg-accent">
              GitHub <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
        <RiskBar score={data.risk_score} threshold={data.threshold} />
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          <Chip tone={data.predicted_degrading ? "risky" : "safe"}>Predicted: {data.predicted_degrading ? "degrading" : "safe"}</Chip>
          {data.label === null
            ? <Chip>True label: unknown (live PR)</Chip>
            : <Chip tone={data.label ? "risky" : "safe"}>True label: {data.label ? "degrading" : "safe"}{data.label_reason ? ` (${data.label_reason.replaceAll("_", " ")})` : ""}</Chip>}
          {data.pr_creates_cycle && <Chip tone="risky">Creates an import cycle</Chip>}
        </div>
      </section>

      <Panel title="Where the score comes from" caption="Each part's contribution to the risk logit. Positive pushes the risk up, negative pushes it down.">
        <DivergingBars rows={[
          { label: "Base (bias)", value: data.layer_a.base },
          { label: "Structure (GNN)", value: data.layer_a.structure_gnn },
          ...(data.layer_a.history !== undefined ? [{ label: "Pre-merge history", value: data.layer_a.history }] : []),
          { label: "Diff text", value: data.layer_a.diff },
        ].map((row) => ({ ...row, value: Number(row.value.toFixed(3)), tone: row.value > 0 ? "risky" as const : "safe" as const }))} />
      </Panel>

      <Panel title="Attribution graph" caption={`The ${data.top_edges.length} edges that moved the score most. Hover a node or edge for details.`}>
        <AttributionGraph edges={data.top_edges} />
      </Panel>

      <Panel title="Module coupling" caption="Afferent (Ca, modules that depend on it) and efferent (Ce, modules it depends on) coupling, before → after the PR.">
        <ModuleTable evidence={data.module_evidence} newCycle={data.new_cycle_modules} />
        {data.structural_delta && (
          <p className="mt-3 text-xs text-muted-foreground">
            Whole-graph change:{" "}
            {Object.entries(data.structural_delta).filter(([, value]) => value !== 0)
              .map(([key, value]) => `${key.replaceAll("_", " ")} ${value > 0 ? "+" : ""}${small(value)}`).join(" · ")
              || "no change to the graph-level metrics"}
          </p>
        )}
      </Panel>

      <Panel title="Top diff hunks" caption="Changed code with the largest effect on the score.">
        <Hunks hunks={data.top_hunks} />
      </Panel>

      <Panel title="Explanation">
        <ExplanationView explanation={data.explanation} />
      </Panel>

      <p className="text-xs text-muted-foreground">
        explainer: {data.explainer} · unfaithfulness {small(data.unfaithfulness)} (lower is better)
      </p>
    </>
  );
}

function Chip({ tone, children }: { tone?: "risky" | "safe"; children: React.ReactNode }) {
  return (
    <span className={cn(
      "rounded-full border px-2.5 py-1",
      tone === "risky" && "border-risky/40 bg-risky/10",
      tone === "safe" && "border-safe/40 bg-safe/10",
      !tone && "border-border bg-muted text-muted-foreground",
    )}>{children}</span>
  );
}

function RiskBar({ score, threshold }: { score: number; threshold: number }) {
  const over = score >= threshold;
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted-foreground">Risk score</span>
        <span className={cn("font-semibold tabular-nums", over ? "text-risky" : "text-safe")}>{score.toFixed(2)}</span>
      </div>
      <div className="relative mt-2 h-3 rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={score}
        aria-label={`Risk score ${score.toFixed(2)}, threshold ${threshold.toFixed(2)}`}>
        <div className={cn("absolute inset-y-0 left-0 rounded-full transition-[width] duration-700", over ? "bg-risky" : "bg-safe")}
          style={{ width: `${Math.min(Math.max(score, 0), 1) * 100}%` }} />
        <div className="absolute -inset-y-1 w-0.5 rounded bg-foreground" style={{ left: `${threshold * 100}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground" style={{ paddingLeft: `max(0px, calc(${threshold * 100}% - 3rem))` }}>
        threshold {threshold.toFixed(2)}
      </p>
    </div>
  );
}

function ModuleTable({ evidence, newCycle }: { evidence: Record<string, ModuleEvidence>; newCycle: string[] }) {
  const entries = Object.entries(evidence ?? {});
  if (!entries.length) return <p className="text-sm text-muted-foreground">No module evidence.</p>;
  const cell = (before: number, after: number) => (
    <span className={cn("tabular-nums", after > before && "font-semibold text-risky", after < before && "font-semibold text-safe")}>
      {before} → {after}
    </span>
  );
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-max text-left text-sm">
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr><th className="px-3 py-2.5 font-medium">Module</th><th className="px-3 py-2.5 font-medium">Ca</th>
            <th className="px-3 py-2.5 font-medium">Ce</th><th className="px-3 py-2.5 font-medium">Import cycle</th></tr>
        </thead>
        <tbody>
          {entries.map(([module, row]) => (
            <tr key={module} className="border-t border-border">
              <td className="px-3 py-2.5 font-mono text-xs">{module}</td>
              <td className="px-3 py-2.5">{cell(row.ca_before, row.ca_after)}</td>
              <td className="px-3 py-2.5">{cell(row.ce_before, row.ce_after)}</td>
              <td className={cn("px-3 py-2.5", newCycle.includes(module) && "font-semibold text-risky")}>
                {row.in_import_cycle ? (newCycle.includes(module) ? "yes, new" : "yes") : "no"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Hunks({ hunks }: { hunks: Hunk[] }) {
  if (!hunks?.length) return <p className="text-sm text-muted-foreground">No hunks for this PR.</p>;
  return (
    <div className="space-y-3">
      {hunks.map((hunk, index) => (
        <details key={index} open={index === 0} className="rounded-xl border border-border">
          <summary className="flex cursor-pointer select-none flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <span className="min-w-0 truncate font-mono text-xs">{hunk.file} : {hunk.lines[0]}–{hunk.lines[1]}</span>
            <span className={cn("text-xs tabular-nums", hunk.effect > 0 ? "text-risky" : "text-safe")}>effect {signed(hunk.effect, 3)}</span>
          </summary>
          <pre className="overflow-x-auto border-t border-border bg-muted py-3 font-mono text-xs leading-5">
            {hunk.snippet.map((line, number) => (
              <div key={number} className={cn("px-4",
                line.startsWith("+") && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                line.startsWith("-") && "bg-red-500/10 text-red-700 dark:text-red-400")}>
                {line || " "}
              </div>
            ))}
          </pre>
        </details>
      ))}
    </div>
  );
}

const RETRIEVAL_MODES: Record<string, string> = {
  signature: "principles retrieved by the attributed edges",
  text: "principles retrieved by the PR title and diff text",
  none: "no principles retrieved",
};

function ExplanationView({ explanation }: { explanation: Explanation | null }) {
  if (!explanation) return <p className="text-sm text-muted-foreground">No explanation generated yet.</p>;
  if (explanation.status === "grounding_failed" || !explanation.explanation) {
    return (
      <p className="text-sm text-muted-foreground">
        The generated explanation failed the grounding check (it cited an edge, principle or number that was not in
        the evidence), so it is not shown.
      </p>
    );
  }
  const suggestion = explanation.suggestion;
  return (
    <div className="space-y-5 text-sm leading-6">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={explanation.verdict === "degrading" ? "risky" : "safe"}>Verdict: {explanation.verdict}</Chip>
        {explanation.principles?.map((principle) => <Chip key={principle}>{principle}</Chip>)}
      </div>
      <Markdown text={explanation.explanation} />
      {!!explanation.retrieved_cards?.length && (
        <div>
          <h4 className="text-sm font-semibold">Why these principles were retrieved</h4>
          <ul className="mt-2 space-y-1.5">
            {explanation.retrieved_cards.map((card) => (
              <li key={card.id} className="text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{card.id}</span>: {card.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!explanation.evidence?.length && (
        <div>
          <h4 className="text-sm font-semibold">Evidence</h4>
          <ul className="mt-2 space-y-2.5">
            {explanation.evidence.map((item, index) => (
              <li key={index} className="rounded-lg border border-border p-3">
                <p className="break-all font-mono text-xs text-muted-foreground">{item.edge}</p>
                <Markdown text={item.why} className="mt-1" />
              </li>
            ))}
          </ul>
        </div>
      )}
      {suggestion && (
        <div>
          <h4 className="text-sm font-semibold">Suggested fix{suggestion.refactoring ? `: ${suggestion.refactoring}` : ""}</h4>
          {!!suggestion.files?.length && <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{suggestion.files.join(", ")}</p>}
          {!!suggestion.steps?.length && <Markdown className="mt-2" text={suggestion.steps.map((step, i) => `${i + 1}. ${step}`).join("\n")} />}
          {suggestion.code_sketch && (
            <pre className="mt-2 overflow-x-auto rounded-lg border border-border bg-muted p-3 font-mono text-xs leading-5">{suggestion.code_sketch}</pre>
          )}
        </div>
      )}
      {explanation.confidence_note && <p className="text-xs text-muted-foreground">{explanation.confidence_note}</p>}
      {explanation.mode && (
        <p className="text-xs text-muted-foreground">
          Generated with {RETRIEVAL_MODES[explanation.mode] ?? explanation.mode}. Passed the grounding check: every
          cited edge, principle and number is in the evidence the model was given.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ attribution graph */

interface GraphNode { id: string; type: string; module: string; name: string; touched: boolean }
interface GraphLink { source: string; target: string; relation: string; attribution: number; added_in_pr: boolean }

// Node types are categorical, so they get hues that stay distinct from the red/blue edge encoding.
const NODE_COLOURS: Record<string, string> = {
  module: "#8b5cf6", class: "#0d9488", function: "#65a30d", method: "#d97706", global_variable: "#db2777",
};
const OTHER_NODE = "#8a8a8a";
const nodeColour = (type: string) => NODE_COLOURS[type] ?? OTHER_NODE;
const EXTERNAL_GROUP = "external (outside the project)";
const isExternal = (type: string) => type.startsWith("external");

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function shortName(id: string) {
  const qualified = id.includes(":") ? id.slice(id.indexOf(":") + 1) : id;
  return qualified.split(".").slice(-1)[0] || qualified;
}

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function AttributionGraph({ edges }: { edges: Edge[] }) {
  const { theme } = useTheme();
  const box = useRef<HTMLDivElement>(null);
  const graph = useRef<ForceGraphMethods<NodeObject<GraphNode>, LinkObject<GraphNode, GraphLink>>>(undefined);
  const [width, setWidth] = useState(600);
  const height = width < 520 ? 320 : 420;

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(260, Math.floor(entry.contentRect.width))));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  // Colours are read from the theme's CSS variables, so the canvas follows light and dark mode.
  const colours = useMemo(() => ({
    risky: cssVar("--chart-risky", "#eb6834"), safe: cssVar("--chart-safe", "#2a78d6"),
    ink: cssVar("--foreground", "#0a0a0a"), muted: cssVar("--muted-foreground", "#6b6b6b"),
    ring: cssVar("--border", "rgba(0,0,0,0.1)"),
  }), [theme]);  // eslint-disable-line react-hooks/exhaustive-deps

  const data = useMemo(() => {
    const nodes = new Map<string, GraphNode>();
    for (const edge of edges) {
      nodes.set(edge.source, { id: edge.source, type: edge.source_type, module: edge.source_module ?? EXTERNAL_GROUP,
        name: shortName(edge.source), touched: edge.touched_source });
      nodes.set(edge.target, { id: edge.target, type: edge.target_type, module: edge.target_module ?? EXTERNAL_GROUP,
        name: shortName(edge.target), touched: edge.touched_target });
    }
    const links: GraphLink[] = edges.map((edge) => ({ source: edge.source, target: edge.target, relation: edge.relation,
      attribution: edge.attribution, added_in_pr: edge.added_in_pr }));
    return { nodes: [...nodes.values()], links };
  }, [edges]);

  const modules = useMemo(() => [...new Set(data.nodes.map((node) => node.module))].sort(), [data]);
  const maxAttribution = Math.max(...edges.map((edge) => Math.abs(edge.attribution)), 1e-9);

  // Pull each node towards its module's anchor on a circle, so modules form visible groups.
  useEffect(() => {
    const instance = graph.current;
    if (!instance) return;
    const radius = modules.length > 1 ? Math.min(width, height) * 0.38 : 0;
    const anchors = new Map(modules.map((module, index) => {
      const angle = (2 * Math.PI * index) / modules.length - Math.PI / 2;
      return [module, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) }];
    }));
    let nodes: NodeObject<GraphNode>[] = [];
    const cluster = Object.assign((alpha: number) => {
      for (const node of nodes) {
        const anchor = anchors.get(node.module);
        if (!anchor) continue;
        node.vx = (node.vx ?? 0) + (anchor.x - (node.x ?? 0)) * 0.4 * alpha;
        node.vy = (node.vy ?? 0) + (anchor.y - (node.y ?? 0)) * 0.4 * alpha;
      }
    }, { initialize: (all: NodeObject<GraphNode>[]) => { nodes = all; } });
    instance.d3Force("cluster", cluster);
    instance.d3Force("charge")?.strength?.(-90);
    instance.d3Force("link")?.strength?.(0.15);  // weak links, so a cross-module edge cannot drag a node out of its group
    instance.d3ReheatSimulation();
  }, [modules, width, height, data]);

  if (!edges.length) return <p className="text-sm text-muted-foreground">No attributed edges.</p>;

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        {Object.entries(NODE_COLOURS).map(([type, colour]) => (
          <span key={type} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: colour }} />{type.replace("_", " ")}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ backgroundColor: OTHER_NODE }} />external (hover for name)
        </span>
      </div>
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 rounded bg-risky" />pushes risk up</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 rounded bg-safe" />pushes risk down</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-muted-foreground" />added in this PR</span>
        <span>thickness = |attribution| · ring = touched by the PR</span>
      </div>
      <div ref={box} className="overflow-hidden rounded-xl border border-border bg-background">
        <ForceGraph2D<GraphNode, GraphLink>
          ref={graph}
          width={width}
          height={height}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)"
          cooldownTicks={120}
          onEngineStop={() => graph.current?.zoomToFit(400, 40)}
          nodeRelSize={5}
          nodeLabel={(node) => `<div style="max-width:22rem"><b>${escapeHtml(node.type)}</b> · ${escapeHtml(node.module)}<br/>${escapeHtml(node.id)}</div>`}
          linkLabel={(link) => {
            const source = typeof link.source === "object" ? (link.source as GraphNode).id : String(link.source);
            const target = typeof link.target === "object" ? (link.target as GraphNode).id : String(link.target);
            return `<div style="max-width:24rem">${escapeHtml(source)}<br/><b>${escapeHtml(link.relation)}</b> → ${escapeHtml(target)}`
              + `<br/>attribution ${signed(link.attribution, 3)}${link.added_in_pr ? " · added in PR" : ""}</div>`;
          }}
          linkColor={(link) => (link.attribution >= 0 ? colours.risky : colours.safe)}
          linkWidth={(link) => 0.8 + (5 * Math.abs(link.attribution)) / maxAttribution}
          linkLineDash={(link) => (link.added_in_pr ? [5, 3] : null)}
          linkDirectionalArrowLength={5}
          linkDirectionalArrowRelPos={0.92}
          linkCurvature={0.12}
          onRenderFramePre={(ctx, scale) => {
            // A faint box around each module group, labelled above it.
            const boxes = new Map<string, { x0: number; y0: number; x1: number; y1: number }>();
            for (const node of data.nodes as NodeObject<GraphNode>[]) {
              const x = node.x ?? 0, y = node.y ?? 0;
              const b = boxes.get(node.module) ?? { x0: x, y0: y, x1: x, y1: y };
              boxes.set(node.module, { x0: Math.min(b.x0, x), y0: Math.min(b.y0, y), x1: Math.max(b.x1, x), y1: Math.max(b.y1, y) });
            }
            const pad = 16;
            ctx.font = `${11 / scale}px Geist Mono, monospace`;
            ctx.textAlign = "left";
            for (const [module, b] of boxes) {
              ctx.strokeStyle = colours.ring;
              ctx.lineWidth = 1 / scale;
              ctx.beginPath();
              ctx.roundRect(b.x0 - pad, b.y0 - pad, b.x1 - b.x0 + 2 * pad, b.y1 - b.y0 + 2 * pad + 8, 8);
              ctx.stroke();
              ctx.fillStyle = colours.muted;
              ctx.fillText(module, b.x0 - pad, b.y0 - pad - 4 / scale);
            }
          }}
          nodeCanvasObject={(node, ctx, scale) => {
            const external = isExternal(node.type);
            const radius = node.type === "module" ? 7 : external ? 3.5 : 5;
            ctx.beginPath();
            ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI);
            ctx.fillStyle = nodeColour(node.type);
            ctx.fill();
            if (node.touched) {
              ctx.lineWidth = 1.6 / scale;
              ctx.strokeStyle = colours.ink;
              ctx.stroke();
            }
            // External nodes are often many short names (append, get, ...): unlabelled, the tooltip names them.
            if (scale > 0.9 && !external) {
              ctx.font = `${10 / scale}px Geist, sans-serif`;
              ctx.textAlign = "center";
              ctx.fillStyle = colours.ink;
              ctx.fillText(node.name, node.x ?? 0, (node.y ?? 0) + radius + 10 / scale);
            }
          }}
          nodePointerAreaPaint={(node, colour, ctx) => {
            ctx.fillStyle = colour;
            ctx.beginPath();
            ctx.arc(node.x ?? 0, node.y ?? 0, 8, 0, 2 * Math.PI);
            ctx.fill();
          }}
        />
      </div>
    </div>
  );
}
