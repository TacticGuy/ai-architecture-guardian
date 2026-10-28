import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/* Styled with the theme tokens, so headings, lists, code and tables follow light and dark mode. */
const components: Components = {
  h1: ({ children }) => <h3 className="mt-4 mb-2 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-4 mb-2 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-3 mb-1.5 text-sm font-semibold first:mt-0">{children}</h4>,
  h4: ({ children }) => <h4 className="mt-3 mb-1.5 text-sm font-semibold first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="my-2 break-words first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4 hover:text-foreground">
      {children}
    </a>
  ),
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>,
  hr: () => <hr className="my-3 border-border" />,
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-muted p-3 font-mono text-xs leading-5">{children}</pre>
  ),
  code: ({ className, children }) => {
    // Fenced blocks carry a language class (or sit inside <pre>, which styles them); inline code gets a chip.
    const block = /language-/.test(className ?? "") || String(children).includes("\n");
    return block
      ? <code className={cn("font-mono", className)}>{children}</code>
      : <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>;
  },
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-max text-left text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted text-muted-foreground">{children}</thead>,
  tr: ({ children }) => <tr className="border-t border-border first:border-t-0">{children}</tr>,
  th: ({ children }) => <th className="px-2.5 py-1.5 font-medium">{children}</th>,
  td: ({ children }) => <td className="px-2.5 py-1.5 tabular-nums">{children}</td>,
};

/** Markdown with GitHub tables/lists; raw HTML in the text is dropped, never rendered. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("min-w-0 break-words", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
