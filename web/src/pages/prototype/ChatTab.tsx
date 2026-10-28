import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "@/components/Markdown";
import { BeamSearch } from "@/components/spectrumui/beam-search";
import { LoadingButton } from "@/components/ui/loading-button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Message { role: "user" | "assistant"; text: string; extra?: string[]; error?: boolean }

function sessionId(): string {
  try {
    let id = sessionStorage.getItem("guardian-chat");
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("guardian-chat", id);
    }
    return id;
  } catch {
    return "default";
  }
}

// Questions that work for every data version (a PR number or "layer C" only exists in some).
const suggestions = ["How is a PR's label decided?", "How well does the fusion model do on the test split?", "What does the risk score mean?"];

export default function ChatTab({ version }: { version: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [id] = useState(sessionId);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, loading]);

  const send = async (text: string) => {
    const asked = text.trim();
    if (!asked || loading) return;
    setQuestion("");
    setMessages((current) => [...current, { role: "user", text: asked }]);
    setLoading(true);
    try {
      const answer = await api.chat(asked, id, version);
      const extra = ["Sources: " + (answer.sources.join(", ") || "none")];
      if (answer.note) extra.push(`Note: ${answer.note}`);
      if (answer.unsupported_numbers.length) extra.push("Numbers not found in the sources: " + answer.unsupported_numbers.join(", "));
      if (answer.unknown_citations.length) extra.push("Cites cards it was not given: " + answer.unknown_citations.join(", "));
      setMessages((current) => [...current, { role: "assistant", text: answer.text, extra }]);
    } catch (exc) {
      setMessages((current) => [...current, { role: "assistant", text: (exc as Error).message, error: true }]);
    } finally {
      setLoading(false);
    }
  };

  const reset = async () => {
    setMessages([]);
    try { await api.chatReset(id, version); } catch { /* the local view is already cleared */ }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm leading-6 text-muted-foreground">
          Answers come only from the project's outputs and cite their sources. Free Groq limits allow about 2-3 questions a minute.
        </p>
        <button type="button" onClick={reset} className="shrink-0 rounded-md border border-input px-3 py-1.5 text-sm transition-colors hover:bg-accent">
          New conversation
        </button>
      </div>

      <div className="mt-5 min-h-[18rem] space-y-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {suggestions.map((text) => (
              <button key={text} type="button" onClick={() => send(text)} className="rounded-full border border-border px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground">
                {text}
              </button>
            ))}
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className={cn("flex animate-fade-up", message.role === "user" && "justify-end")}>
            <div
              className={cn(
                "max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-6",
                message.role === "user" ? "bg-primary text-primary-foreground" : "border border-border bg-card",
                message.error && "border-destructive/50 bg-destructive/10",
              )}
            >
              {message.role === "assistant" && !message.error
                ? <Markdown text={message.text} />
                : <p className="whitespace-pre-wrap break-words">{message.text}</p>}
              {message.extra?.map((line) => <p key={line} className="mt-2 break-words text-xs text-muted-foreground">{line}</p>)}
            </div>
          </div>
        ))}
        {loading && <p className="animate-pulse text-sm text-muted-foreground">Thinking</p>}
        <div ref={endRef} />
      </div>

      <div className="sticky bottom-4 mt-6 flex items-center gap-2 rounded-2xl bg-background/90 py-2 backdrop-blur">
        <BeamSearch
          value={question} onChange={setQuestion} onSubmit={send}
          placeholder="Ask about a PR, the model, the data or the method"
        />
        <LoadingButton type="button" loading={loading} disabled={!question.trim()} onClick={() => send(question)} aria-label="Send question" className="size-12 shrink-0 rounded-xl p-0">
          {!loading && <Send className="size-4" />}
        </LoadingButton>
      </div>
    </div>
  );
}
