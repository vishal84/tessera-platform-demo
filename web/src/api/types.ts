// Mirrors services/console: response shapes and SSE event payloads.

export type Persona = "sre" | "swe" | "ds" | "claude" | "system";
export type Verdict = "healthy" | "degraded" | "unknown";
export type IncidentStatus = "open" | "triaging" | "pr_open" | "merged" | "recovered";

export interface SimResult {
  offered_rps: number;
  capacity_rps: number;
  utilization: number;
  cache_hit_rate: number;
  mean_attempts_per_call: number;
  p99_latency_seconds: number;
  success_rate: number;
  saturated: boolean;
}

export interface GatewayHealth {
  ref: string;
  sha: string | null;
  verdict: Verdict;
  config?: Record<string, number | boolean | null>;
  result?: SimResult;
  error?: string;
  branch?: string;
}

export interface HealthSnapshot {
  production: GatewayHealth;
  working_tree: GatewayHealth;
  slo: { success_rate: number; p99_seconds: number };
  checked_at: string;
  seq?: number;
}

export interface ConsoleHealth {
  status: string;
  repo: { root: string; head: string; branch: string; clean: boolean };
  claude: { bin: string; version: string | null };
  jupyter: { url: string; reachable: boolean };
  run: { active: boolean; run_id: string | null };
  provider: "local" | "github";
  persona: Persona;
}

export interface IncidentSummary {
  id: string;
  severity: string;
  service: string;
  title: string;
  created_at: string;
  status: IncidentStatus;
}

export interface MetricRow {
  ts: string;
  fraud_model_rps: number;
  cache_hit_rate: number;
  p99_latency_seconds: number;
  auth_success_rate: number;
}

export interface Marker { ts: string; kind: "deploy" | "inflection" | "alert"; label: string }
export interface Deploy { service: string; started: string; finished: string; revision: string; deployed_by: string }
export interface LogLine { ts: string; level: string; service: string; event: string; [key: string]: unknown }

export interface Alert {
  incident_id: string;
  created_at: string;
  severity: string;
  service: string;
  title: string;
  source: string;
  triggered_conditions?: Array<Record<string, unknown>>;
  impacted?: Record<string, number>;
  runbook?: string;
  dashboards?: string[];
}

export interface IncidentBundle extends IncidentSummary {
  alert: Alert;
  metrics: MetricRow[];
  deploys: Deploy[];
  logs: LogLine[];
  traces: { trace_id?: string; spans?: Array<Record<string, unknown>> };
  markers: Marker[];
  files: Array<{ name: string; bytes: number; lines: number }>;
  readme: string;
}

export type RunStatus = "running" | "cancelling" | "finished" | "failed" | "cancelled";

export type Track = "incident" | "model";

export interface RunMeta {
  run_id: string;
  incident_id: string | null;   // null for a model run
  track: Track;
  subject_id: string;
  mode: "live" | "replay";
  status: RunStatus;
  started_at: string;
  ended_at: string | null;
  session_id: string | null;
  argv: string[];
  recording: string | null;
  speed: number;
  replayed: boolean;
  num_turns: number | null;
  cost_usd: number | null;
  duration_ms: number | null;
  branch: string | null;
  pr_id: string | null;
  error: { kind: string; message: string; stderr_tail?: string } | null;
  phases: string[];
  type?: string;
  seq?: number;
}

export type ActivityType = "session" | "text" | "tool_call" | "tool_result" | "hook" | "phase" | "result" | "raw" | "system" | "thinking" | "permission_denied";

export interface ActivityEvent {
  seq: number;
  ts: string;
  run_id: string;
  agent: string;
  type: ActivityType;
  replayed?: boolean;
  parent_tool_use_id?: string;
  // tool_call
  tool_use_id?: string;
  tool?: string | null;
  summary?: string;
  input?: Record<string, unknown>;
  // tool_result
  is_error?: boolean;
  preview?: string;
  // text / result
  text?: string;
  result_text?: string;
  subtype?: string;
  num_turns?: number;
  cost_usd?: number;
  duration_ms?: number;
  // hook
  hook_event_name?: string;
  hook_name?: string;
  tool_name?: string;
  decision?: "allow" | "deny" | null;
  exit_code?: number | null;
  stderr_head?: string;
  // phase
  phase?: string;
  index?: number;
  // permission_denied / thinking
  reason?: string;
  message?: string;
  tokens?: number;
  // session
  model?: string;
  permission_mode?: string;
  tools?: string[];
  raw?: string;
}

export interface AuditEvent {
  seq?: number;
  ts: string;
  hook: "protect_secrets" | "pii_scan";
  event: string | null;
  session_id: string | null;
  agent_type?: string | null;
  tool_name: string | null;
  target: string | null;
  decision: "allow" | "deny" | "warn";
  reason: string | null;
  source: "run" | "desktop" | "replay";
  run_id: string | null;
}

export interface TimelineEvent {
  id: string;
  ts: string;
  type: string;
  persona: Persona;
  title: string;
  detail: string | null;
  refs: Record<string, string | null | undefined>;
  seq?: number;
}

export interface Commit { sha: string; short: string; author: string; date: string; subject: string }
export interface FileStat { path: string; additions: number; deletions: number }

export interface PullRequest {
  id: string;
  provider: "local" | "github";
  title: string;
  branch: string;
  base: string;
  state: "open" | "merged" | "closed";
  number: number | null;
  url: string | null;
  created_at: string | null;
  head_sha: string | null;
  body_md: string;
  commits: Commit[];
  files: FileStat[];
  path: string | null;
  incident_id: string | null;
  ticket: string | null;
  track: Track;
}

export interface Recording {
  name: string;
  source: "golden" | "run";
  path: string;
  incident_id: string | null;
  track: Track;
  subject_id: string | null;
  recorded_at: string | null;
  duration_s: number;
  num_events: number;
  num_turns: number | null;
  cost_usd: number | null;
  has_branch: boolean;
  has_pr: boolean;
  branch: string | null;
}

export interface RunContract {
  prompt: string;
  prompt_parts: string[];
  track: Track;
  model: string | null;
  allowed_tools: string;
  max_turns: number;
  source: string;
  argv: string[];
  provider: "local" | "github";
}

export interface Policy {
  deny: string[];
  allow: string[];
  hooks: Array<{ event: string; matcher: string | null; command: string | null }>;
  selftests: Record<string, { passed: number | null; failed: number; exit_code: number }>;
  ci_mirror: Array<{ workflow: string; job: string; step: string | null; command: string }>;
}

export type GateStatus = "queued" | "running" | "pass" | "blocked" | "not_implemented" | "error";

export interface GateEvent {
  seq?: number;
  ts?: string;
  gate_run_id: string;
  model: string;
  gate: "leakage" | "performance" | "drift" | "fairness" | "model_card";
  command: string;
  status: GateStatus;
  exit_code?: number | null;
  stdout_tail?: string;
  duration_s?: number;
}

export interface ModelEntry {
  name: string;
  role: "champion" | "candidate";
  status: string;
  deployed?: string;
  auc_holdout?: number;
  pr_auc_holdout?: number;
  features?: number | string[];
  shadow_report?: string;
  notebook?: string;
  owner?: string;
  ticket?: string;
}

export interface Registry {
  champion: ModelEntry | null;
  candidates: ModelEntry[];
  from: string;
  model_card_present: boolean;
  validation_present: boolean;
}

export interface ShadowReport {
  model: string;
  champion: string;
  generated_at: string;
  window: { start: string; end: string; scored_transactions: number; labels: string };
  offline: { auc: number; pr_auc: number; source: string };
  shadow: { auc: number; pr_auc: number; by_month: Array<{ month: string; n: number; auc: number }> };
  champion_same_window: { auc: number; pr_auc: number };
  features: string[];
  feature_serving: Record<string, { source: string; computed_from: string }>;
  feature_stats: Record<string, { training_nonzero_share: number; shadow_nonzero_share: number }>;
  status: string;
  reason: string;
  ticket: string;
}

export interface ApiErrorBody { error: { code: string; message: string; details?: unknown } }
