import type {
  ActivityEvent, AuditEvent, ConsoleHealth, GateEvent, HealthSnapshot, IncidentBundle, IncidentSummary,
  Persona, Policy, PullRequest, Recording, Registry, RunContract, RunMeta, ShadowReport, TimelineEvent,
  Track,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let code = "http_error", message = response.statusText, details: unknown;
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
      details = body?.error?.details;
    } catch { /* non-JSON error body */ }
    throw new ApiError(response.status, code, message, details);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body: JSON.stringify(body) });

export const client = {
  health: () => api<ConsoleHealth>("/health"),
  gatewayHealth: () => api<HealthSnapshot>("/gateway/health"),
  incidents: () => api<IncidentSummary[]>("/incidents"),
  incident: (id: string) => api<IncidentBundle>(`/incidents/${id}`),

  runs: () => api<RunMeta[]>("/runs"),
  run: (id: string) => api<RunMeta>(`/runs/${id}`),
  runEvents: (id: string, after = 0) => api<ActivityEvent[]>(`/runs/${id}/events?after=${after}`),
  runContract: (track: Track = "incident") => api<RunContract>(`/runs/contract?track=${track}`),
  startLive: (subject_id: string, track: Track = "incident") =>
    post<RunMeta>("/runs", { subject_id, track, mode: "live" }),
  startReplay: (subject_id: string, recording = "golden", speed = 4, track: Track = "incident") =>
    post<RunMeta>("/runs", { subject_id, track, mode: "replay", recording, speed }),
  cancelRun: (id: string) => post<RunMeta>(`/runs/${id}/cancel`),
  setSpeed: (id: string, speed: number) => post<RunMeta>(`/runs/${id}/speed`, { speed }),
  recordings: () => api<Recording[]>("/recordings"),

  prs: () => api<PullRequest[]>("/prs"),
  prDiff: (id: string) => api<{ diff: string; stat: PullRequest["files"] }>(`/prs/${id}/diff`),
  requestReview: (id: string, persona: Persona = "swe") =>
    post<{ ok: boolean; prompt: string; pr: PullRequest }>(`/prs/${id}/review-request`, { persona }),
  mergePR: (id: string, persona: Persona = "swe") =>
    post<{ merged_sha: string; production: HealthSnapshot["production"] }>(`/prs/${id}/merge`, { persona }),

  timeline: () => api<TimelineEvent[]>("/timeline"),
  postTimeline: (event: { type: string; persona: Persona; title: string; detail?: string; refs?: Record<string, unknown> }) =>
    post<TimelineEvent>("/timeline", event),
  setPersona: (persona: Persona) => post<{ persona: Persona }>("/persona", { persona }),

  policy: () => api<Policy>("/guardrails/policy"),
  audit: (limit = 300) => api<AuditEvent[]>(`/guardrails/audit?limit=${limit}`),

  models: () => api<Registry>("/models"),
  modelContract: (name: string) => api<RunContract>(`/models/${name}/contract`),
  shadow: (name: string) => api<ShadowReport>(`/models/${name}/shadow`),
  notebookUrl: (name: string) => api<{ url: string; exists: boolean; jupyter_reachable: boolean; path: string }>(`/models/${name}/notebook-url`),
  runGates: (name: string) => post<{ gate_run_id: string; gates: Array<{ gate: string; command: string }> }>(`/models/${name}/gates`, { persona: "ds" }),
  gates: (name: string) => api<GateEvent[]>(`/models/${name}/gates`),
  proof: (name: string) => post<{ exit_code: number; tests: Array<{ name: string; outcome: string }>; output: string }>(`/models/${name}/proof`),
};
