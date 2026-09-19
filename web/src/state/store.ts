/*
 * One external store fed by one EventSource. Pages read slices with useStore();
 * actions call the client and let the stream update state. On (re)connect the
 * snapshots are refetched and deltas applied by sequence number, so a page
 * reload mid-demo lands on the same picture.
 */
import { useEffect, useSyncExternalStore } from "react";
import { client } from "../api/client";
import type {
  ActivityEvent, AuditEvent, GateEvent, HealthSnapshot, IncidentSummary, PullRequest, Recording,
  RunMeta, TimelineEvent,
} from "../api/types";

export interface State {
  connected: boolean;
  health: HealthSnapshot | null;
  incidents: IncidentSummary[];
  runs: RunMeta[];
  activeRun: RunMeta | null;      // running / cancelling, else the most recent
  activity: ActivityEvent[];     // events of activeRun
  audit: AuditEvent[];
  timeline: TimelineEvent[];
  prs: PullRequest[];
  recordings: Recording[];
  gates: Record<string, GateEvent[]>;   // keyed by model name; latest status per gate
  lastSeq: number;
}

const initial: State = {
  connected: false, health: null, incidents: [], runs: [], activeRun: null, activity: [],
  audit: [], timeline: [], prs: [], recordings: [], gates: {}, lastSeq: 0,
};

let state: State = initial;
const listeners = new Set<() => void>();

function set(patch: Partial<State> | ((s: State) => Partial<State>)) {
  const next = typeof patch === "function" ? patch(state) : patch;
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function getState() { return state; }

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => selector(state), () => selector(state));
}

function pickActive(runs: RunMeta[]): RunMeta | null {
  const live = runs.find((r) => r.status === "running" || r.status === "cancelling");
  if (live) return live;
  return runs.length ? runs[runs.length - 1] : null;
}

function upsertRun(runs: RunMeta[], run: RunMeta): RunMeta[] {
  const index = runs.findIndex((r) => r.run_id === run.run_id);
  const { type: _type, seq: _seq, ...meta } = run;
  if (index === -1) return [...runs, meta as RunMeta];
  const next = runs.slice();
  next[index] = { ...next[index], ...meta };
  return next;
}

export async function refreshSnapshots() {
  const [health, incidents, runs, prs, timeline, audit, recordings] = await Promise.all([
    client.gatewayHealth(), client.incidents(), client.runs(), client.prs(), client.timeline(),
    client.audit(), client.recordings(),
  ]);
  const activeRun = pickActive(runs);
  const activity = activeRun ? await client.runEvents(activeRun.run_id) : [];
  set({ health, incidents, runs, activeRun, activity, prs, timeline, audit, recordings });
}

export const actions = {
  refreshPRs: async () => set({ prs: await client.prs(), incidents: await client.incidents() }),
  refreshHealth: async () => set({ health: await client.gatewayHealth() }),
  refreshRuns: async () => {
    const runs = await client.runs();
    set({ runs, activeRun: pickActive(runs) });
  },
  refreshRecordings: async () => set({ recordings: await client.recordings() }),
  refreshGates: async (model: string) => {
    const gates = await client.gates(model);
    set((s) => ({ gates: { ...s.gates, [model]: gates } }));
  },
  selectRun: async (run: RunMeta) => {
    const activity = await client.runEvents(run.run_id);
    set({ activeRun: run, activity });
  },
};

function applyGate(gates: GateEvent[], event: GateEvent): GateEvent[] {
  const next = gates.filter((g) => g.gate !== event.gate || g.gate_run_id === event.gate_run_id);
  const index = next.findIndex((g) => g.gate === event.gate && g.gate_run_id === event.gate_run_id);
  if (index === -1) return [...next, event];
  next[index] = event;
  return next;
}

let source: EventSource | null = null;

function connect() {
  if (source) return;
  source = new EventSource("/api/events");
  source.onopen = () => { set({ connected: true }); void refreshSnapshots(); };
  source.onerror = () => set({ connected: false });

  const on = <T,>(channel: string, handler: (data: T) => void) =>
    source!.addEventListener(channel, (e) => {
      const data = JSON.parse((e as MessageEvent).data) as T & { seq?: number };
      if (data.seq !== undefined && data.seq <= state.lastSeq) return;
      if (data.seq !== undefined) set({ lastSeq: data.seq });
      handler(data);
    });

  on<RunMeta>("run", (run) => {
    set((s) => {
      const runs = upsertRun(s.runs, run);
      const isActive = !s.activeRun || s.activeRun.run_id === run.run_id || run.type === "run_started";
      const activeRun = isActive ? runs.find((r) => r.run_id === run.run_id) ?? s.activeRun : s.activeRun;
      const activity = run.type === "run_started" ? [] : s.activity;
      return { runs, activeRun, activity };
    });
    if (run.type === "run_finished" || run.type === "run_failed" || run.type === "run_cancelled") {
      void actions.refreshPRs();
      void actions.refreshHealth();
      // A live run leaves a recording behind. Without this the run you just
      // made is missing from the picker until someone reloads the page.
      void actions.refreshRecordings();
    }
  });
  on<ActivityEvent>("activity", (event) => {
    set((s) => (s.activeRun && event.run_id === s.activeRun.run_id ? { activity: [...s.activity, event] } : {}));
  });
  on<AuditEvent>("audit", (event) => set((s) => ({ audit: [...s.audit.slice(-999), event] })));
  on<TimelineEvent>("timeline", (event) => {
    set((s) => ({ timeline: [...s.timeline, event] }));
    if (event.type === "merged" || event.type === "recovered" || event.type === "pr_opened") void actions.refreshPRs();
  });
  on<HealthSnapshot>("health", (health) => set({ health }));
  on<{ type: string; pr: PullRequest }>("pr", () => { void actions.refreshPRs(); });
  on<GateEvent>("gate", (event) => set((s) => ({ gates: { ...s.gates, [event.model]: applyGate(s.gates[event.model] ?? [], event) } })));
}

/** Mount once, at the app root. */
export function useEventSource() {
  useEffect(() => { connect(); }, []);
}
