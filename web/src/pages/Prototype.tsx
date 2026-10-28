import { motion } from "framer-motion";
import { Bot, GitPullRequest, LayoutDashboard, Network, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Footer } from "@/components/Footer";
import { NavBar } from "@/components/NavBar";
import { Notice } from "@/components/kit";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import AttributionTab from "@/pages/prototype/AttributionTab";
import ChatTab from "@/pages/prototype/ChatTab";
import ExplorerTab from "@/pages/prototype/ExplorerTab";
import LiveTab from "@/pages/prototype/LiveTab";
import OverviewTab from "@/pages/prototype/OverviewTab";

const tabs = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "explorer", label: "PR explorer", icon: Search },
  { id: "live", label: "Live GitHub PR", icon: GitPullRequest },
  { id: "chat", label: "Ask the chatbot", icon: Bot },
  { id: "attribution", label: "Attribution (v5)", icon: Network },
] as const;
type TabId = (typeof tabs)[number]["id"];

export default function Prototype() {
  const [tab, setTab] = useState<TabId>("overview");
  const [versions, setVersions] = useState<string[]>([]);
  const [version, setVersion] = useState<string>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.versions()
      .then((result) => {
        setVersions(result.versions);
        setVersion(result.default ?? undefined);
        if (!result.default) setError("No knowledge base found. Build one with: python scripts/build_kb.py --manifest artifacts/gnn_embeddings_<version>.json");
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <NavBar />
      <main className="mx-auto max-w-6xl px-4 pb-24 pt-10 sm:px-6">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-2xl">
              <p className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">Prototype</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">AI Architecture Guardian</h1>
              <p className="mt-3 leading-7 text-muted-foreground">
                Predicts, before a Python PR is merged, whether the code it touches will become more tightly coupled
                over the next six months, and explains why.{" "}
                <Link to="/" className="underline underline-offset-4 hover:text-foreground">About the project</Link>
              </p>
            </div>
            {versions.length > 0 && (
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                Data version
                <select
                  value={version} onChange={(event) => setVersion(event.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
                >
                  {versions.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </label>
            )}
          </div>
        </motion.div>

        <div role="tablist" aria-label="Prototype sections" className="mt-8 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-border">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
              className={cn(
                "relative flex shrink-0 items-center gap-2 px-4 py-3 text-sm font-medium transition-colors",
                tab === id ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-4" /> {label}
              {tab === id && (
                <motion.span layoutId="tab-underline" className="absolute inset-x-0 bottom-0 h-0.5 bg-foreground" />
              )}
            </button>
          ))}
        </div>

        <div className="mt-8">
          {error && tab !== "attribution" && <Notice kind="error">{error}</Notice>}
          {tab === "attribution" && <AttributionTab />}
          {version && tab !== "attribution" && (
            <motion.div key={`${tab}-${version}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
              {tab === "overview" && <OverviewTab version={version} />}
              {tab === "explorer" && <ExplorerTab version={version} />}
              {tab === "live" && <LiveTab version={version} />}
              {tab === "chat" && <ChatTab version={version} />}
            </motion.div>
          )}
        </div>
      </main>
      <Footer />
    </div>
  );
}
