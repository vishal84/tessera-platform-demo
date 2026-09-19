import { useEffect, useRef, useState } from "react";
import type { ActivityEvent } from "../api/types";
import { elapsed, shortPath, usd } from "../lib/fmt";
import { phaseMeta } from "./PhaseStepper";
import { PersonaChip, StatusPill } from "./primitives";

const TOOL_GLYPH: Record<string, string> = {
  Read: "≡", Grep: "⌕", Glob: "✱", Bash: "$", Edit: "✎", Write: "＋", MultiEdit: "✎", NotebookEdit: "▤", Task: "⇉", Skill: "/",
};

function Narration({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 260;
  return (
    <div className="rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm text-text-2">
      <span className="whitespace-pre-wrap">{open || !long ? text : text.slice(0, 260) + "…"}</span>
      {long && <button className="ml-2 text-xs text-accent" onClick={() => setOpen((o) => !o)}>{open ? "less" : "more"}</button>}
    </div>
  );
}

export function ActivityFeed({ events, startedAt, running }: { events: ActivityEvent[]; startedAt?: string | null; running: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  useEffect(() => {
    if (stick && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events.length, stick]);

  const t0 = startedAt ? new Date(startedAt).getTime() : events.length ? new Date(events[0].ts).getTime() : 0;
  const results = new Map<string, ActivityEvent>();
  const denied = new Set<string>();
  let hooksAllowed = 0, hooksDenied = 0, noise = 0;
  for (const e of events) {
    if (e.type === "tool_result" && e.tool_use_id) results.set(e.tool_use_id, e);
    if (e.type === "permission_denied" && e.tool_use_id) denied.add(e.tool_use_id);
    if (e.type === "hook" && e.decision === "allow") hooksAllowed++;
    if (e.type === "hook" && e.decision === "deny") hooksDenied++;
    if (e.type === "thinking" || e.type === "raw" || e.type === "system") noise++;
  }
  const last = events[events.length - 1];
  const thinking = running && last?.type === "thinking";

  return (
    <div className="flex h-full flex-col">
      <div ref={box} className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1"
        onScroll={(e) => { const el = e.currentTarget; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40); }}>
        {events.length === 0 && <div className="py-8 text-center text-sm text-text-muted">{running ? "Waiting for the first tool call…" : "No run yet. Start one above."}</div>}
        {events.map((e) => {
          const at = t0 ? elapsed(new Date(e.ts).getTime() - t0) : "";
          if (e.type === "phase") {
            const meta = phaseMeta(e.phase as string);
            return <div key={e.seq} className="flex items-center gap-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-text-muted"><span className="h-px flex-1 bg-border" />phase · {meta?.label ?? e.phase}<span className="h-px flex-1 bg-border" /></div>;
          }
          if (e.type === "text" && e.text) return <div key={e.seq}><Narration text={e.text} /></div>;
          if (e.type === "tool_call") {
            const result = e.tool_use_id ? results.get(e.tool_use_id) : undefined;
            const isDenied = e.tool_use_id ? denied.has(e.tool_use_id) : false;
            const status = isDenied ? "denied" : result ? (result.is_error ? "error" : "ok") : running ? "pending" : "—";
            const summary = ["Read", "Write", "Edit", "MultiEdit", "NotebookEdit"].includes(e.tool ?? "") ? shortPath(e.summary) : e.summary;
            return (
              <div key={e.seq} className="rounded-md border border-border bg-surface px-2.5 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="mono w-12 shrink-0 text-[11px] text-text-muted">{at}</span>
                  <span className="mono inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm bg-surface-2 text-[11px] text-text-2">{TOOL_GLYPH[e.tool ?? ""] ?? "·"}</span>
                  <span className="w-20 shrink-0 text-xs font-semibold">{e.tool}</span>
                  {e.agent !== "main" && <PersonaChip persona="claude" small />}
                  {e.agent !== "main" && <span className="text-[11px] text-text-muted">{e.agent}</span>}
                  <span className="mono min-w-0 flex-1 truncate text-xs text-text" title={e.summary}>{summary}</span>
                  <span className="shrink-0">
                    {status === "ok" && <StatusPill tone="good">ok</StatusPill>}
                    {status === "error" && <StatusPill tone="critical">error</StatusPill>}
                    {status === "denied" && <StatusPill tone="warning">not allowed</StatusPill>}
                    {status === "pending" && <StatusPill tone="info" pulse>running</StatusPill>}
                  </span>
                </div>
                {result?.preview && !isDenied && (
                  <div className={`mono mt-1 truncate pl-[3.6rem] text-[11px] ${result.is_error ? "text-status-critical" : "text-text-muted"}`} title={result.preview}>{result.preview.split("\n")[0]}</div>
                )}
              </div>
            );
          }
          if (e.type === "permission_denied") {
            return (
              <div key={e.seq} className="flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs" style={{ borderColor: "color-mix(in srgb, var(--status-warning) 50%, var(--color-border))" }}>
                <span className="mono w-12 shrink-0 text-[11px] text-text-muted">{at}</span>
                <StatusPill tone="warning">allowlist</StatusPill>
                <span className="text-text-2"><b className="text-text">{e.tool_name}</b> is not in <span className="mono">--allowedTools</span>; denied automatically — nobody is there to approve it.</span>
              </div>
            );
          }
          if (e.type === "hook" && e.decision === "deny") {
            return (
              <div key={e.seq} className="flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs" style={{ borderColor: "color-mix(in srgb, var(--status-critical) 55%, var(--color-border))" }}>
                <span className="mono w-12 shrink-0 text-[11px] text-text-muted">{at}</span>
                <StatusPill tone="critical">guardrail</StatusPill>
                <span className="text-text-2">{e.hook_event_name} hook blocked <b className="text-text">{e.tool_name}</b>. <span className="mono">{e.stderr_head?.split("\n")[0]}</span></span>
              </div>
            );
          }
          if (e.type === "result") {
            return (
              <div key={e.seq} className="mt-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-text-2">
                <span className="font-semibold text-text">{e.is_error ? "Run ended with an error" : "Run finished"}</span>
                {" · "}{e.num_turns ?? "?"} turns · {elapsed(e.duration_ms)} · {usd(e.cost_usd)}
                {e.result_text && <div className="mt-1 whitespace-pre-wrap text-text-2">{e.result_text.slice(0, 600)}</div>}
              </div>
            );
          }
          return null;
        })}
        {thinking && <div className="flex items-center gap-2 py-1 text-xs text-text-muted"><span className="pulse h-1.5 w-1.5 rounded-full bg-accent" />thinking…</div>}
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-[11px] text-text-muted">
        <span>{hooksAllowed} hook checks passed{hooksDenied ? `, ${hooksDenied} blocked` : ""} · {noise} heartbeat/system lines hidden</span>
        {!stick && <button className="text-accent" onClick={() => setStick(true)}>jump to latest ↓</button>}
      </div>
    </div>
  );
}
