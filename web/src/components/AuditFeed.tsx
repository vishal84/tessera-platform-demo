import { useState } from "react";
import type { AuditEvent } from "../api/types";
import { clock } from "../lib/fmt";
import { Empty, StatusPill, type Tone } from "./primitives";

const TONE: Record<AuditEvent["decision"], Tone> = { deny: "critical", warn: "warning", allow: "good" };
const SOURCE: Record<AuditEvent["source"], string> = { run: "headless run", desktop: "desktop session", replay: "recording" };

export function AuditFeed({ events, defaultShowAllowed = false, limit = 200 }: { events: AuditEvent[]; defaultShowAllowed?: boolean; limit?: number }) {
  const [showAllowed, setShowAllowed] = useState(defaultShowAllowed);
  const counts = { deny: 0, warn: 0, allow: 0 };
  for (const e of events) counts[e.decision] = (counts[e.decision] ?? 0) + 1;
  const shown = events.filter((e) => showAllowed || e.decision !== "allow").slice(-limit).reverse();
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-text-2">
        <StatusPill tone="critical">{counts.deny} denied</StatusPill>
        <StatusPill tone="warning">{counts.warn} warned</StatusPill>
        <StatusPill tone="good">{counts.allow} allowed</StatusPill>
        <label className="ml-auto flex items-center gap-1.5"><input type="checkbox" checked={showAllowed} onChange={(e) => setShowAllowed(e.target.checked)} />show allowed</label>
      </div>
      {shown.length === 0 && <Empty>No {showAllowed ? "" : "blocked or flagged "}tool calls yet. Every Edit, Write, Read and Bash the agent attempts passes through the hooks and lands here.</Empty>}
      <ul className="divide-y divide-border">
        {shown.map((e, i) => (
          <li key={e.seq ?? `${e.ts}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-xs">
            <span className="mono w-16 text-text-muted">{clock(e.ts)}</span>
            <StatusPill tone={TONE[e.decision]}>{e.decision}</StatusPill>
            <span className="w-24 font-semibold">{e.tool_name ?? "—"}</span>
            <span className="mono min-w-0 flex-1 truncate" title={e.target ?? ""}>{e.target ?? ""}</span>
            <span className="text-text-muted">{e.hook}</span>
            <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-2">{SOURCE[e.source]}{e.agent_type ? ` · ${e.agent_type}` : ""}</span>
            {e.reason && e.decision !== "allow" && <span className="basis-full pl-[4.5rem] text-text-2">matched <span className="mono">{e.reason}</span></span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
