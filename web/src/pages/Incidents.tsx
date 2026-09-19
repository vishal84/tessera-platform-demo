import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { client } from "../api/client";
import type { IncidentBundle } from "../api/types";
import { ActivityFeed } from "../components/ActivityFeed";
import { CodeBlock, Markdown } from "../components/CodeBlock";
import { PhaseStepper } from "../components/PhaseStepper";
import { PRCard } from "../components/PRCard";
import { RunControls } from "../components/RunControls";
import { Timeline } from "../components/Timeline";
import { Card, Empty, StatusPill, type Tone } from "../components/primitives";
import { utcClock } from "../lib/fmt";
import { useStore } from "../state/store";

const STATUS_TONE: Record<string, Tone> = { open: "critical", triaging: "info", pr_open: "warning", merged: "good", recovered: "good" };
const STATUS_LABEL: Record<string, string> = { open: "open — no owner", triaging: "Claude triaging", pr_open: "PR awaiting review", merged: "merged", recovered: "recovered" };

export default function Incidents() {
  const { id = "INC-4412" } = useParams();
  const [bundle, setBundle] = useState<IncidentBundle | null>(null);
  const [tab, setTab] = useState<"alert" | "deploys" | "logs" | "traces" | "readme">("deploys");
  const [now, setNow] = useState(Date.now());
  const incidents = useStore((s) => s.incidents);
  const run = useStore((s) => s.activeRun);
  const activity = useStore((s) => s.activity);
  const prs = useStore((s) => s.prs);
  const recordings = useStore((s) => s.recordings);
  const timeline = useStore((s) => s.timeline);

  useEffect(() => { client.incident(id).then(setBundle).catch(() => setBundle(null)); }, [id]);
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);

  const status = incidents.find((i) => i.id === id)?.status ?? bundle?.status ?? "open";
  const myRun = run && run.incident_id === id ? run : null;
  const myPRs = prs.filter((p) => p.incident_id === id);
  const running = myRun?.status === "running" || myRun?.status === "cancelling";

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{id}</h1>
            {bundle && <StatusPill tone="critical">{bundle.alert.severity}</StatusPill>}
            <StatusPill tone={STATUS_TONE[status] ?? "neutral"} pulse={status === "triaging"}>{STATUS_LABEL[status] ?? status}</StatusPill>
          </div>
          <div className="text-sm text-text-2">{bundle?.alert.title} · {bundle?.alert.service} · paged {bundle ? utcClock(bundle.alert.created_at) : ""} UTC</div>
        </div>
      </header>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Evidence bundle" actions={
          <div className="flex gap-1 text-xs">
            {(["deploys", "alert", "logs", "traces", "readme"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`rounded-sm px-2 py-0.5 ${tab === t ? "bg-surface-2 font-semibold" : "text-text-2 hover:bg-surface-2"}`}>{t}</button>
            ))}
          </div>}>
          {!bundle ? <div className="text-sm text-text-muted">Loading…</div> : (
            <>
              <div className="mb-2 flex flex-wrap gap-2 text-[11px] text-text-muted">{bundle.files.map((f) => <span key={f.name} className="mono rounded-sm bg-surface-2 px-1.5 py-0.5">{f.name} · {f.lines} lines</span>)}</div>
              {tab === "deploys" && (
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-text-muted"><th className="py-1">service</th><th>started</th><th>finished</th><th>revision</th><th>by</th></tr></thead>
                  <tbody>{bundle.deploys.map((d) => (
                    <tr key={d.revision} className={`border-t border-border ${d.service === bundle.alert.service ? "font-semibold" : ""}`}>
                      <td className="py-1">{d.service}</td><td className="mono">{d.started.slice(11, 19)}</td><td className="mono">{d.finished.slice(11, 19)}</td><td className="mono">{d.revision}</td><td>{d.deployed_by}</td>
                    </tr>))}</tbody>
                </table>
              )}
              {tab === "alert" && <CodeBlock code={JSON.stringify(bundle.alert, null, 2)} maxHeight={360} language="json" />}
              {tab === "logs" && (
                <div className="max-h-96 overflow-auto rounded-md border border-border bg-surface-2 p-2 text-[11px]">
                  {bundle.logs.map((l, i) => (
                    <div key={i} className={`mono whitespace-nowrap ${l.level === "ERROR" ? "text-status-critical" : l.level === "WARN" ? "text-status-warning" : "text-text-2"}`}>
                      {l.ts} {l.level.padEnd(5)} {l.event} {Object.entries(l).filter(([k]) => !["ts", "level", "service", "event"].includes(k)).map(([k, v]) => `${k}=${String(v)}`).join(" ")}
                    </div>))}
                </div>
              )}
              {tab === "traces" && <CodeBlock code={JSON.stringify(bundle.traces, null, 2)} maxHeight={360} language="json" />}
              {tab === "readme" && <div className="max-h-96 overflow-auto pr-1"><Markdown text={bundle.readme} /></div>}
            </>
          )}
        </Card>
        {/* Untagged events are shared context and still belong here; the data
            scientist's are not, and they carry a track of their own. */}
        <Card title="Timeline"><Timeline events={timeline.filter((e) => e.refs?.track !== "model" && (!e.refs?.incident_id || e.refs.incident_id === id))} limit={14} dense /></Card>
      </div>

      <Card title="Triage" actions={<span className="text-xs text-text-muted">{myRun ? `${activity.filter((e) => e.type === "tool_call").length} tool calls` : "no run"}</span>}>
        <div className="space-y-4">
          <RunControls subjectId={id} run={myRun} recordings={recordings} />
          <PhaseStepper run={myRun} activity={myRun ? activity : []} now={now} />
          <div className="h-[28rem]">
            <ActivityFeed events={myRun ? activity : []} startedAt={myRun?.started_at} running={!!running} />
          </div>
        </div>
      </Card>

      {myPRs.length > 0 ? myPRs.map((pr) => <PRCard key={pr.id} pr={pr} />) : (
        <Card title="Pull request"><Empty>No PR yet. When the run commits on <span className="mono">incident/{id}-…</span> and writes its description, it appears here for review.</Empty></Card>
      )}

    </div>
  );
}
