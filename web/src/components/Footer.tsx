import { GithubIcon, REPO_URL } from "@/components/GithubIcon";
import { Logo } from "@/components/Logo";
import { Link } from "react-router-dom";

export function Footer() {
  return (
  <footer className="border-t border-border">
    <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[2fr_1fr_1fr]">
      <div className="max-w-sm">
        <div className="flex items-center gap-3">
          <Logo className="size-9 rounded-lg ring-1 ring-border" />
          <span className="font-display text-sm font-medium uppercase tracking-[0.12em]">AI Architecture Guardian</span>
        </div>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          Static analysis, graph learning and explainable AI for Python pull requests.
        </p>
      </div>
      <nav aria-label="Project">
        <h4 className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">Project</h4>
        <ul className="mt-4 space-y-2.5 text-sm">
          {[["Features", "/#features"], ["Technology", "/#technology"], ["Limits", "/#limits"]].map(([label, href]) => (
            <li key={href}><a href={href} className="transition-colors hover:text-muted-foreground">{label}</a></li>
          ))}
          <li><Link to="/prototype" className="transition-colors hover:text-muted-foreground">Prototype</Link></li>
        </ul>
      </nav>
      <nav aria-label="Resources">
        <h4 className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">Resources</h4>
        <ul className="mt-4 space-y-2.5 text-sm">
          <li>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 transition-colors hover:text-muted-foreground">
              <GithubIcon className="size-4" /> GitHub repository
            </a>
          </li>
        </ul>
      </nav>
    </div>
    <div className="border-t border-border">
      <p className="mx-auto max-w-6xl px-4 py-5 text-xs text-muted-foreground sm:px-6">
        Risk scores are uncalibrated model outputs, not validated probabilities.
      </p>
    </div>
  </footer>
  );
}
