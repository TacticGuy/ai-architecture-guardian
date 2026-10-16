import { AlertTriangle, Info } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({ title, caption, children, className }: {
  title?: string; caption?: string; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-border bg-card p-5 sm:p-6", className)}>
      {title && <h3 className="text-base font-semibold tracking-tight">{title}</h3>}
      {caption && <p className="mt-1 text-sm leading-6 text-muted-foreground">{caption}</p>}
      <div className={cn(title || caption ? "mt-5" : "")}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: {
  label: string; value: ReactNode; hint?: string; tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1.5 text-2xl font-semibold tracking-tight", tone === "bad" && "text-risky", tone === "good" && "text-safe")}>
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "error"; children: ReactNode }) {
  const Icon = kind === "info" ? Info : AlertTriangle;
  return (
    <div
      role={kind === "error" ? "alert" : undefined}
      className={cn(
        "flex gap-3 rounded-xl border p-4 text-sm leading-6",
        kind === "info" && "border-border bg-muted text-muted-foreground",
        kind === "warn" && "border-risky/40 bg-risky/10 text-foreground",
        kind === "error" && "border-destructive/50 bg-destructive/10 text-foreground",
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

export function DataTable({ rows, columns }: { rows: Record<string, string | number>[]; columns?: string[] }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">No rows.</p>;
  const keys = columns ?? Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-max text-left text-sm">
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>{keys.map((key) => <th key={key} className="whitespace-nowrap px-3 py-2.5 font-medium">{key}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-border transition-colors hover:bg-muted/60">
              {keys.map((key) => <td key={key} className="whitespace-nowrap px-3 py-2.5 tabular-nums">{row[key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Legend({ items }: { items: { label: string; className: string }[] }) {
  return (
    <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", item.className)} />{item.label}
        </span>
      ))}
    </div>
  );
}

/** Bars that grow from a centre line: negative to the left, positive to the right. */
export function DivergingBars({ rows }: {
  rows: { label: string; value: number; tone: "safe" | "risky"; detail?: string }[];
}) {
  const max = Math.max(...rows.map((row) => Math.abs(row.value)), 1e-9);
  return (
    <ul className="space-y-2.5">
      {rows.map((row) => (
        <li key={row.label} className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-3 sm:grid-cols-[minmax(0,14rem)_1fr_4.5rem]">
          <span className="truncate text-sm" title={row.label}>{row.label}</span>
          <div className="relative h-4 rounded-sm bg-muted" title={row.detail}>
            <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
            <div
              className={cn("absolute inset-y-0 rounded-sm transition-[width] duration-700 ease-out", row.tone === "risky" ? "bg-risky" : "bg-safe")}
              style={{
                width: `${(Math.abs(row.value) / max) * 50}%`,
                left: row.value >= 0 ? "50%" : `${50 - (Math.abs(row.value) / max) * 50}%`,
              }}
            />
          </div>
          <span className="text-right text-xs tabular-nums text-muted-foreground">{row.value > 0 ? "+" : ""}{row.value}</span>
        </li>
      ))}
    </ul>
  );
}
