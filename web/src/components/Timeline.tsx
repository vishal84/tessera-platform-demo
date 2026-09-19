import type { TimelineEvent } from "../api/types";
import { clock } from "../lib/fmt";
import { PERSONA_LABEL, PersonaChip, personaColor } from "./primitives";

export function Timeline({ events, limit, dense }: { events: TimelineEvent[]; limit?: number; dense?: boolean }) {
  const shown = limit ? events.slice(-limit) : events;
  if (!shown.length) return <div className="text-sm text-text-muted">Nothing has happened yet. Replay the telemetry to fire the alert.</div>;
  return (
    <ol className="relative ml-2 border-l border-border">
      {shown.map((e, i) => {
        const prev = shown[i - 1];
        const handoff = prev && prev.persona !== e.persona && e.persona !== "system";
        const c = personaColor(e.persona);
        return (
          <li key={e.id} className={`relative pl-5 ${dense ? "py-1.5" : "py-2.5"}`}>
            <span className="absolute -left-[5px] top-[14px] h-2.5 w-2.5 rounded-full ring-2 ring-surface" style={{ background: c }} />
            {handoff && <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: c }}>→ hand-off to {PERSONA_LABEL[e.persona]}</div>}
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="mono text-[11px] text-text-muted">{clock(e.ts)}</span>
              <PersonaChip persona={e.persona} small />
              <span className={`font-medium ${dense ? "text-sm" : "text-sm"}`}>{e.title}</span>
            </div>
            {e.detail && !dense && <div className="mt-0.5 text-xs text-text-2">{e.detail}</div>}
          </li>
        );
      })}
    </ol>
  );
}
