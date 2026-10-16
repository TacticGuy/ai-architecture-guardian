export interface Headline {
  fusion_f1: number; baseline_f1: number; fusion_ap: number; baseline_ap: number; threshold: number; test_prs: number;
}
export interface ScoreRow {
  PR: string; sample_id: string; "Risk score": number; "True label": string; Prediction: string; Correct: string;
}
export interface Overview {
  version: string; headline: Partial<Headline>; threshold: number; dataset_count: number; warnings: string[];
  results: Record<string, string | number>[]; scores: ScoreRow[];
  splits: { Split: string; PRs: number; "Risky (1)": number; "Safe (0)": number }[]; purged: string[];
}
export interface PrMeta {
  sample_id: string; pr_number: number; split: string; label: number; probability: number; explained?: boolean;
  label_text: string;
}
export interface LayerARow { Part: string; Logit: number; Direction: string }
export interface HunkRow {
  File: string; Lines: string; "Effect on risk": number; Added: number; Removed: number; snippet: string;
}
export interface LayerCRow { File: string; Effect: number; "Touched by PR": string; Nodes: number }
export interface PrDetail {
  sample_id: string; probability: number; label: number; threshold: number; correct: boolean; card: string;
  explained: boolean;
  explanation: null | {
    layer_a: LayerARow[]; layer_b: HunkRow[]; note: string;
    layer_c: null | { touched_total: number; untouched_total: number; files: LayerCRow[] };
  };
}
export interface LiveReport {
  sample_id: string; url: string; title: string; risk_percent: number; classification: string;
  gnn_probability: number; threshold: number; warning: string; layer_a: LayerARow[]; hunks: HunkRow[];
  saved_path: string;
}
export interface ChatAnswer {
  text: string; sources: string[]; note: string; unsupported_numbers: string[]; unknown_citations: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new Error("Cannot reach the API. Start it with: uvicorn api.main:app --port 8000");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Invalid request.";
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const qs = (params: Record<string, string | undefined>) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => value && query.set(key, value));
  const text = query.toString();
  return text ? `?${text}` : "";
};

export const api = {
  versions: () => request<{ versions: string[]; default: string | null }>("/api/versions"),
  overview: (version?: string) => request<Overview>(`/api/overview${qs({ version })}`),
  prs: (version?: string) => request<{ version: string; threshold: number; prs: PrMeta[] }>(`/api/prs${qs({ version })}`),
  prDetail: (sampleId: string, version?: string) =>
    request<PrDetail>(`/api/prs/detail${qs({ sample_id: sampleId, version })}`),
  live: (url: string, maxHunks: number, version?: string) =>
    request<LiveReport>("/api/live", post({ url, max_hunks: maxHunks, version })),
  chat: (question: string, sessionId: string, version?: string) =>
    request<ChatAnswer>("/api/chat", post({ question, session_id: sessionId, version })),
  chatReset: (sessionId: string, version?: string) =>
    request<{ status: string }>("/api/chat/reset", post({ session_id: sessionId, version })),
};
