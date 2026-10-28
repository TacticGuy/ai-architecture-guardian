import {
  ArrowRight, Bot, Braces, Cpu, FileCode2, GitPullRequest, History, Layers, Network, Orbit, Scale, ScanSearch,
  Server, Sparkles, Gauge, Workflow, Globe, Atom, FolderGit2, Sigma, Boxes, Lock, type LucideIcon,
} from "lucide-react";
import { motion } from "framer-motion";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Footer } from "@/components/Footer";
import { NavBar } from "@/components/NavBar";
import { AnimatedCard } from "@/components/spectrumui/animated-card";
import { BeamCard } from "@/components/spectrumui/beam-card";
import { LoadingButton } from "@/components/ui/loading-button";

const features = [
  {
    icon: <Network className="size-5" />, eyebrow: "Structure",
    title: "Validated dependency graphs",
    description:
      "Python source is parsed with the AST, never executed. Modules, classes, functions, methods and module-level variables become a typed graph with CONTAINS, IMPORTS, CALLS, INHERITS and ACCESSES_GLOBAL edges, checked against PyCG and grimp.",
  },
  {
    icon: <History className="size-5" />, eyebrow: "Target",
    title: "Forward-looking labels",
    description:
      "A PR is labelled degrading when, in the six months after it is merged, the modules it touched gain dependencies faster than the rest of their project, or join a new import cycle. No one hand-labels it.",
  },
  {
    icon: <Orbit className="size-5" />, eyebrow: "Learning",
    title: "Heterogeneous GNN",
    description:
      "A GraphSAGE network reads the graph with the PR applied, pools the touched files and their neighbours, and adds 13 pre-merge history numbers. Its score is the mean of five trained seeds.",
  },
  {
    icon: <FileCode2 className="size-5" />, eyebrow: "Semantics",
    title: "Diff understanding",
    description:
      "The production-code diff of each PR is embedded with the CodeReviewer encoder. Late fusion weighs it against the GNN, with the weight chosen on validation projects.",
  },
  {
    icon: <Scale className="size-5" />, eyebrow: "Rigour",
    title: "Fair comparisons",
    description:
      "6,141 PRs from 40 projects, with whole projects held out for testing. The GNN is reported next to always-risky, diff-only, history, CodeScene-style hotspot, radon, pylint and SonarQube baselines.",
  },
  {
    icon: <ScanSearch className="size-5" />, eyebrow: "Explainability",
    title: "Edge-level explanations",
    description:
      "Integrated Gradients splits each score over the dependencies that produced it. The attribution graph shows which edges pushed the risk up or down, with a faithfulness check.",
  },
  {
    icon: <Sparkles className="size-5" />, eyebrow: "Explanation",
    title: "Explanations in plain words",
    description:
      "Design principles are retrieved by the attributed edges, not by the wording of a question. The LLM's explanation and fix are rejected if they cite an edge, principle or number that was not supplied.",
  },
  {
    icon: <Bot className="size-5" />, eyebrow: "Assistant",
    title: "Grounded chatbot",
    description:
      "Retrieval over a knowledge base built from the project outputs. Answers cite their source cards, and numbers not found in those sources are flagged.",
  },
  {
    icon: <GitPullRequest className="size-5" />, eyebrow: "Inference",
    title: "Live GitHub PR analysis",
    description:
      "Paste a public pull request URL, open, merged or closed. The app rebuilds the right before and after code, embeds the diff and scores it. Live reports are never added to training data.",
  },
];

const technologies = [
  { icon: <Braces className="size-7" />, title: "Python AST", about: "Parses repository source into symbols, imports and calls without running any target code." },
  { icon: <Atom className="size-7" />, title: "PyTorch", about: "Trains and runs the GNN encoder, the auxiliary classifier and the fusion model." },
  { icon: <Network className="size-7" />, title: "PyTorch Geometric", about: "Holds each repository as HeteroData and provides the heterogeneous GraphSAGE layers." },
  { icon: <Cpu className="size-7" />, title: "Transformers", about: "Loads Microsoft CodeReviewer to embed the diff of every pull request." },
  { icon: <Globe className="size-7" />, title: "GitHub API", about: "Fetches live pull requests and their merge commits through httpx." },
  { icon: <Sparkles className="size-7" />, title: "Groq LLM", about: "Writes the chatbot's answers and the PR explanations from retrieved cards only." },
  { icon: <Gauge className="size-7" />, title: "Code-quality tools", about: "radon, pylint and SonarQube scored every PR's touched files as industry baselines." },
  { icon: <Server className="size-7" />, title: "FastAPI", about: "Serves model results, attributions, live analysis and chat to this interface." },
  { icon: <Workflow className="size-7" />, title: "React", about: "Builds this interface with Tailwind CSS, React Router, Framer Motion and a force-directed graph view." },
];

interface Step { icon: LucideIcon; title: string; detail: string }
const phases: { label: string; note: string; steps: Step[] }[] = [
  {
    label: "Static analysis", note: "Locked pipeline, steps 1 to 5",
    steps: [
      { icon: FolderGit2, title: "Clone repositories", detail: "Each repository is cloned and recorded with its HEAD commit." },
      { icon: Braces, title: "Parse with the AST", detail: "Modules, classes, functions, imports and calls, without executing code." },
      { icon: Network, title: "Build the dependency graph", detail: "Typed nodes joined by CONTAINS, IMPORTS, CALLS, INHERITS and ACCESSES_GLOBAL edges." },
      { icon: Sigma, title: "Compute node features", detail: "Size, complexity, parameters and degrees, named and inspectable." },
      { icon: Boxes, title: "Convert to HeteroData", detail: "A fixed schema of 7 node types and 46 edge types for PyTorch Geometric." },
    ],
  },
  {
    label: "Learn and explain", note: "Scoring and explanation",
    steps: [
      { icon: Orbit, title: "Encode structure", detail: "GraphSAGE pools the touched files and their neighbours, plus pre-merge history." },
      { icon: FileCode2, title: "Encode the diff", detail: "CodeReviewer embeds the production-code changes of the PR." },
      { icon: Layers, title: "Fuse and score", detail: "Late fusion turns both views into one risk score." },
      { icon: ScanSearch, title: "Attribute", detail: "Integrated Gradients ranks the dependencies behind the score." },
      { icon: Sparkles, title: "Explain in words", detail: "Principles retrieved by those edges, and an LLM answer checked against them." },
    ],
  },
];

function Section({ id, eyebrow, title, intro, children }: {
  id?: string; eyebrow: string; title: string; intro?: string; children: ReactNode;
}) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6 sm:py-24">
      <motion.div
        initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }} className="mb-12 max-w-2xl"
      >
        <p className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">{eyebrow}</p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h2>
        {intro && <p className="mt-4 leading-7 text-muted-foreground">{intro}</p>}
      </motion.div>
      {children}
    </section>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const [opening, setOpening] = useState(false);

  // Loads the prototype's code first (a real network fetch), then navigates. Loading ends if it fails.
  const openPrototype = async () => {
    setOpening(true);
    try {
      await import("@/pages/Prototype");
    } finally {
      setOpening(false);
    }
    navigate("/prototype");
  };

  return (
    <div className="min-h-screen bg-white text-neutral-950 dark:bg-background dark:text-foreground">
      <NavBar
        links={[
          { label: "Features", href: "#features" },
          { label: "Technology", href: "#technology" },
          { label: "Limits", href: "#limits" },
        ]}
      />

      <main>
        <section className="relative overflow-hidden">
          <div className="grid-bg pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto max-w-6xl px-4 pb-20 pt-20 sm:px-6 sm:pb-28 sm:pt-28">
            <motion.h1
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.08 }}
              className="chroma-text chroma-text-animate mb-[calc(1rem-0.25em)] max-w-[640px] text-balance pb-[0.25em] pt-[0.12em] font-spectral text-[30px] font-light capitalize leading-[0.95] tracking-[-0.09em] sm:text-[42px] lg:max-w-[760px] lg:text-[54px] lg:leading-[51px] lg:tracking-[-3px]"
            >
              Know which pull requests will tangle your architecture.
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.16 }}
              className="mt-6 max-w-2xl text-lg leading-8 text-muted-foreground"
            >
              AI Architecture Guardian predicts, before a Python PR is merged, whether the code it touches will
              become more tightly coupled over the next six months, and explains why. A graph neural network reads
              the repository's dependency structure, Integrated Gradients points to the dependencies behind the
              score, and a grounded LLM explains them with design principles.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.24 }}
              className="mt-9 flex flex-wrap items-center gap-3"
            >
              <a
                href="#features"
                className="inline-flex h-11 items-center gap-2 rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
              >
                Explore the project <ArrowRight className="size-4" />
              </a>
              <a
                href="#how"
                className="inline-flex h-11 items-center rounded-md border border-input px-6 text-sm font-medium transition-colors hover:bg-accent"
              >
                How it works
              </a>
            </motion.div>
          </div>
        </section>

        <Section
          id="how" eyebrow="Pipeline" title="From source code to an explained score"
          intro="A locked static-analysis pipeline turns each repository into a graph. The models then read that graph together with the PR diff and its recent history, score the risk, trace it to individual dependencies and explain it."
        >
          <div className="grid gap-6 lg:grid-cols-[5fr_4fr]">
            {phases.map((phase, phaseIndex) => (
              <motion.div
                key={phase.label}
                initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.5, delay: phaseIndex * 0.1 }}
                className="rounded-2xl border border-border bg-card p-6 sm:p-7"
              >
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold tracking-tight">{phase.label}</h3>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-1 font-mono text-[11px] text-muted-foreground">
                    {phaseIndex === 0 && <Lock className="size-3" />}{phase.note}
                  </span>
                </div>
                <ol className="relative mt-7">
                  <motion.span
                    aria-hidden initial={{ scaleY: 0 }} whileInView={{ scaleY: 1 }} viewport={{ once: true }}
                    transition={{ duration: 1.2, ease: "easeOut" }}
                    className="absolute bottom-5 left-5 top-5 w-px origin-top bg-gradient-to-b from-foreground/40 via-foreground/20 to-transparent"
                  />
                  {phase.steps.map((step, index) => {
                    const Icon = step.icon;
                    const number = phaseIndex === 0 ? index + 1 : phases[0].steps.length + index + 1;
                    return (
                      <motion.li
                        key={step.title}
                        initial={{ opacity: 0, x: -12 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-20px" }}
                        transition={{ duration: 0.45, delay: index * 0.1 }}
                        className="group relative flex gap-4 pb-6 last:pb-0"
                      >
                        <span className="relative z-10 flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-background shadow-sm transition-all duration-300 group-hover:-translate-y-0.5 group-hover:border-foreground/40 group-hover:bg-primary group-hover:text-primary-foreground">
                          <Icon className="size-[18px]" />
                        </span>
                        <div className="min-w-0 pt-0.5">
                          <p className="flex items-baseline gap-2 text-[15px] font-medium">
                            <span className="font-mono text-xs text-muted-foreground">{String(number).padStart(2, "0")}</span>
                            {step.title}
                          </p>
                          <p className="mt-1 text-sm leading-6 text-muted-foreground">{step.detail}</p>
                        </div>
                      </motion.li>
                    );
                  })}
                </ol>
              </motion.div>
            ))}
          </div>
        </Section>

        <Section
          id="features" eyebrow="Features" title="What the system does"
          intro="Every capability below is implemented in this project and available in the prototype."
        >
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature, index) => (
              <motion.div
                key={feature.title} className="flex"
                initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.5, delay: (index % 3) * 0.07, ease: [0.22, 1, 0.36, 1] }}
              >
                <BeamCard
                  size={index % 2 ? "pulse-inner" : "md"} colorVariant={index % 2 ? "mono" : "ocean"}
                  eyebrow={feature.eyebrow} title={feature.title} description={feature.description}
                  className="flex h-full flex-col"
                >
                  <span className="flex size-9 items-center justify-center rounded-lg border border-border bg-muted text-foreground">
                    {feature.icon}
                  </span>
                </BeamCard>
              </motion.div>
            ))}
          </div>
        </Section>

        <Section
          id="technology" eyebrow="Technology" title="Built with"
          intro="The libraries and services this project actually uses, from static analysis to the interface you are looking at."
        >
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {technologies.map((tech, index) => (
              <AnimatedCard key={tech.title} index={index} icon={tech.icon} title={tech.title} aboutProduct={tech.about} />
            ))}
          </div>
        </Section>

        <Section
          id="limits" eyebrow="Honest limits" title="What the numbers do and do not mean"
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div className="rounded-2xl border border-border bg-card p-6">
              <h3 className="font-semibold tracking-tight">An outcome proxy</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                The label measures how the touched modules' coupling grows in the six months after the merge. Other
                PRs merged in that time change those modules too, so a degrading label does not prove this PR caused it.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-card p-6">
              <h3 className="font-semibold tracking-tight">Uncalibrated scores</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                The risk percentage is the model score times 100, not a validated probability. Read the bootstrap
                ranges rather than single numbers, and compare against the always-risky baseline and the industry tools.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-card p-6">
              <h3 className="font-semibold tracking-tight">Static analysis has blind spots</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Dynamic imports, reflection and calls through values in containers are invisible to the AST. Measured
                against PyCG, the graph's call edges are precise but miss calls that only value tracking can find.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-card p-6">
              <h3 className="font-semibold tracking-tight">Explanations describe the model</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Edge attributions show what drove the model's score, not the real cause of later coupling growth.
                Suggested fixes are starting points for a reviewer, not verified refactorings.
              </p>
            </div>
          </div>
        </Section>

        <section className="border-t border-border">
          <div className="mx-auto flex max-w-6xl flex-col items-center px-4 py-24 text-center sm:px-6">
            <motion.h2
              initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
              transition={{ duration: 0.5 }} className="max-w-xl text-3xl font-semibold tracking-tight sm:text-4xl"
            >
              See it work on real pull requests
            </motion.h2>
            <p className="mt-4 max-w-lg leading-7 text-muted-foreground">
              Browse model results, trace a PR's score to the dependencies behind it, analyse a live GitHub PR, or
              ask the chatbot.
            </p>
            <LoadingButton size="lg" loading={opening} onClick={openPrototype} className="mt-8 h-12 gap-2 px-8 text-base">
              {opening ? "Loading prototype" : <>Open the prototype <ArrowRight className="ml-2 size-4" /></>}
            </LoadingButton>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
