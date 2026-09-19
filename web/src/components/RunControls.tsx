import { useEffect, useState } from "react";
import { ApiError, client } from "../api/client";
import type { Persona, Recording, RunContract, RunMeta, Track } from "../api/types";
import { elapsed, usd } from "../lib/fmt";
import { CodeBlock } from "./CodeBlock";
import { Button, StatusPill } from "./primitives";

export function RunControls({ subjectId, run, recordings, track = "incident", persona = "sre", liveLabel = "Triage with Claude" }: {
  subjectId: string;
  run: RunMeta | null;
  recordings: Recording[];
  track?: Track;
  persona?: Persona;
  liveLabel?: string;
}) {
  const [error, setError] = useState<{ message: string; details?: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState("golden");
  const [speed, setSpeed] = useState(4);
  const [contract, setContract] = useState<RunContract | null>(null);
  const [showContract, setShowContract] = useState(false);
  const active = run !== null && (run.status === "running" || run.status === "cancelling");
  const mine = recordings.filter((r) => r.track === track && (!r.subject_id || r.subject_id === subjectId));
  const hasGolden = mine.some((r) => r.source === "golden");
  const runs = mine.filter((r) => r.source === "run");

  // Before a beat has a committed recording there is no golden to fall back on,
  // and leaving the picker on it means Play stays dead with a playable run
  // sitting in the list. Select the latest run instead, until a golden exists.
  useEffect(() => {
    if (recording === "golden" && !hasGolden && runs.length) setRecording(runs[runs.length - 1].name);
    if (recording !== "golden" && hasGolden && !mine.some((r) => r.name === recording)) setRecording("golden");
  }, [hasGolden, runs.length, recording]);

  const guard = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); }
    catch (e) {
      if (e instanceof ApiError) setError({ message: e.message, details: Array.isArray(e.details) ? e.details as string[] : e.details ? [JSON.stringify(e.details)] : undefined });
      else setError({ message: String(e) });
    } finally { setBusy(false); }
  };
  const toggleContract = async () => {
    if (!contract) setContract(await client.runContract(track));
    setShowContract((s) => !s);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" persona={persona} disabled={active || busy} onClick={() => guard(() => client.startLive(subjectId, track))}>
          {liveLabel}
        </Button>
        <span className="text-xs text-text-muted">headless · same flags as the GitHub Action</span>
        <span className="mx-1 h-5 w-px bg-border" />
        <select value={recording} onChange={(e) => setRecording(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm">
          <option value="golden">golden recording{hasGolden ? "" : " (none yet)"}</option>
          {runs.map((r) => <option key={r.name} value={r.name}>{r.name} · {elapsed(r.duration_s * 1000)}</option>)}
        </select>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm">
          {[1, 4, 8, 16].map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
        <Button disabled={active || busy || (recording === "golden" && !hasGolden)} onClick={() => guard(() => client.startReplay(subjectId, recording, speed, track))}>Play recording</Button>
        {active && <Button variant="danger" onClick={() => guard(() => client.cancelRun(run!.run_id))}>Cancel</Button>}
        <Button variant="ghost" onClick={toggleContract}>{showContract ? "Hide command" : "Show the command"}</Button>
      </div>

      {!mine.length && (
        // The incident beat ships a committed recording, so it never shows this.
        // The model beat starts empty, and an inert button explains nothing.
        <div className="text-xs text-text-muted">
          Nothing recorded for <span className="mono">{subjectId}</span> yet. Start a live run — it is recorded
          automatically and becomes replayable here as soon as it finishes.
        </div>
      )}

      {run && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-2">
          {run.status === "running" && <StatusPill tone="info" pulse>{run.replayed ? "replaying" : "live"}</StatusPill>}
          {run.status === "cancelling" && <StatusPill tone="warning" pulse>cancelling</StatusPill>}
          {run.status === "finished" && <StatusPill tone="good">finished</StatusPill>}
          {run.status === "failed" && <StatusPill tone="critical">failed · {run.error?.kind}</StatusPill>}
          {run.status === "cancelled" && <StatusPill tone="neutral">cancelled</StatusPill>}
          <span className="mono">{run.run_id}</span>
          {run.session_id && <span>session <span className="mono">{run.session_id.slice(0, 8)}</span></span>}
          {run.num_turns != null && <span>{run.num_turns} turns · {usd(run.cost_usd)}</span>}
          {run.branch && <span>branch <span className="mono">{run.branch}</span></span>}
        </div>
      )}

      {run?.status === "failed" && (
        <div className="rounded-md border p-3 text-sm" style={{ borderColor: "color-mix(in srgb, var(--status-critical) 50%, var(--color-border))" }}>
          <div className="font-semibold">The live run failed ({run.error?.kind}).</div>
          <div className="mt-1 text-text-2">{run.error?.message}</div>
          {run.error?.stderr_tail && <pre className="mt-2 max-h-32 overflow-auto rounded-sm bg-surface-2 p-2 text-[11px]">{run.error.stderr_tail}</pre>}
          <div className="mt-2 flex gap-2">
            <Button variant="primary" disabled={!hasGolden} onClick={() => guard(() => client.startReplay(subjectId, "golden", speed, track))}>Play the golden recording at {speed}×</Button>
          </div>
        </div>
      )}

      {run?.session_id && !run.replayed && run.status !== "running" && (
        <div className="text-xs text-text-muted">Pick this conversation up in a terminal: <span className="mono rounded-sm bg-surface-2 px-1">claude --resume {run.session_id}</span></div>
      )}

      {error && (
        <div className="rounded-md border p-3 text-sm" style={{ borderColor: "color-mix(in srgb, var(--status-warning) 60%, var(--color-border))" }}>
          <div className="font-semibold">{error.message}</div>
          {error.details && <ul className="mt-1 list-disc pl-5 text-text-2">{error.details.map((d, i) => <li key={i}>{d}</li>)}</ul>}
        </div>
      )}

      {showContract && contract && (
        <div className="space-y-2">
          <div className="text-xs text-text-2">Prompt, tool allowlist and turn budget are read from <span className="mono">{contract.source}</span> at run time — the console cannot drift from the automation it stands in for. Provider: <b>{contract.provider}</b>{contract.provider === "local" && " (PR is written to .tessera/prs/, not to the remote)"}.</div>
          <CodeBlock label="argv" wrap code={contract.argv.map((a) => (a.includes(" ") || a.includes("\n") ? JSON.stringify(a) : a)).join(" \\\n  ")} />
        </div>
      )}
    </div>
  );
}
