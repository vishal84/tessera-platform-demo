import type { GateEvent, GateStatus } from "../api/types";
import { StatusPill, type Tone } from "./primitives";

const LABEL: Record<GateStatus, string> = { queued: "queued", running: "running", pass: "PASS", blocked: "BLOCKED", not_implemented: "NOT IMPLEMENTED", error: "ERROR" };
const TONE: Record<GateStatus, Tone> = { queued: "neutral", running: "info", pass: "good", blocked: "critical", not_implemented: "warning", error: "serious" };

export function GateCard({ title, description, gate, command }: { title: string; description: string; gate?: GateEvent; command?: string }) {
  const status = gate?.status;
  return (
    <div className="rounded-md border border-border bg-surface p-3 shadow-1" style={{ borderTop: `3px solid ${status ? `var(--status-${TONE[status]})` : "var(--color-border)"}` }}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">{title}</div>
        {status ? <StatusPill tone={TONE[status]} pulse={status === "running"}>{LABEL[status]}</StatusPill> : <StatusPill tone="neutral">not run</StatusPill>}
      </div>
      <div className="mt-0.5 text-xs text-text-2">{description}</div>
      <div className="mono mt-2 truncate text-[11px] text-text-muted" title={gate?.command ?? command}>{gate?.command ?? command}</div>
      {status === "not_implemented" && <div className="mt-1 text-[11px] text-text-2">module missing — tracked as TESS-2310</div>}
      {gate?.stdout_tail && status !== "not_implemented" && <pre className="mt-2 max-h-28 overflow-auto rounded-sm bg-surface-2 p-2 text-[11px] text-text-2">{gate.stdout_tail}</pre>}
    </div>
  );
}
