import type { ActivityEvent, RunMeta, Track } from "../api/types";
import { elapsed } from "../lib/fmt";

export type Phase = { key: string; label: string; hint: string };

/**
 * What counts as progress, per track. The keys must match the phase tuples in
 * services/console/stream_json.py, and must stay unique across both tables --
 * `phaseMeta` looks a phase up without knowing which run it came from.
 */
export const PHASE_TABLES: Record<Track, Phase[]> = {
  incident: [
    { key: "evidence", label: "Evidence", hint: "reads the bundle" },
    { key: "correlate", label: "Correlate", hint: "git log / show" },
    { key: "prove", label: "Prove", hint: "capacity model" },
    { key: "fix", label: "Fix", hint: "config & client" },
    { key: "test", label: "Test", hint: "fails before, passes after" },
    { key: "runbook", label: "Runbook", hint: "what the next responder needs" },
    { key: "pr", label: "PR", hint: "branch, commit, description" },
  ],
  model: [
    { key: "shadow", label: "Shadow", hint: "0.906 offline, 0.699 live" },
    { key: "reproduce", label: "Reproduce", hint: "the notebook, executed" },
    { key: "leakage", label: "Leakage", hint: "the chargeback aggregate" },
    { key: "aggregates", label: "Point-in-time", hint: "ml/features/aggregates.py" },
    { key: "gates", label: "Gates", hint: "ml/validation/*" },
    { key: "card", label: "Model card", hint: "MRM will not review without one" },
    { key: "pr", label: "PR", hint: "branch, commit, description" },
  ],
};

// The incident beat was here first and other modules import this name.
export const PHASES = PHASE_TABLES.incident;

export function phasesFor(track: Track | undefined | null): Phase[] {
  return PHASE_TABLES[track ?? "incident"] ?? PHASE_TABLES.incident;
}

/** A phase's label and hint, whichever track it belongs to. */
export function phaseMeta(phaseKey: string): Phase | undefined {
  for (const table of Object.values(PHASE_TABLES)) {
    const found = table.find((p) => p.key === phaseKey);
    if (found) return found;
  }
  return undefined;
}

/**
 * `track` is passed explicitly because the stepper is on screen before any run
 * exists -- and an empty stepper showing the other beat's steps is worse than
 * no stepper at all. The run, once there, still wins.
 */
export function PhaseStepper({ run, activity, now, track = "incident" }: {
  run: RunMeta | null; activity: ActivityEvent[]; now: number; track?: Track;
}) {
  const phases = phasesFor(run?.track ?? track);
  const phaseEvents = activity.filter((e) => e.type === "phase");
  const times = new Map(phaseEvents.map((e) => [e.phase as string, new Date(e.ts).getTime()]));
  const order = phaseEvents.map((e) => e.phase as string);
  const running = run?.status === "running";
  const end = run?.ended_at ? new Date(run.ended_at).getTime() : now;
  return (
    <ol className="grid gap-1" style={{ gridTemplateColumns: `repeat(${phases.length}, minmax(0, 1fr))` }}>
      {phases.map((phase) => {
        const started = times.get(phase.key);
        const position = order.indexOf(phase.key);
        const next = position >= 0 && position < order.length - 1 ? times.get(order[position + 1]) : undefined;
        const state = started === undefined ? "pending" : position === order.length - 1 && running ? "current" : "done";
        const color = state === "done" ? "var(--status-good)" : state === "current" ? "var(--color-accent)" : "var(--color-border)";
        return (
          <li key={phase.key} className="rounded-md border border-border bg-surface px-2 py-1.5" style={{ borderTop: `3px solid ${color}` }}>
            <div className="flex items-center justify-between gap-1">
              <span className={`text-xs font-semibold ${state === "pending" ? "text-text-muted" : "text-text"}`}>{phase.label}</span>
              {state === "current" && <span className="pulse h-1.5 w-1.5 rounded-full" style={{ background: color }} />}
            </div>
            <div className="text-[10px] text-text-muted">{phase.hint}</div>
            <div className="mono mt-0.5 text-[11px] text-text-2">{started === undefined ? "—" : elapsed((next ?? end) - started)}</div>
          </li>
        );
      })}
    </ol>
  );
}
