import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { client } from "../api/client";
import type { IncidentBundle } from "../api/types";
import { Button, Card, MetricTile, StatusPill } from "../components/primitives";
import { Timeline } from "../components/Timeline";
import { TimeSeriesChart, markerIndex } from "../components/TimeSeriesChart";
import { num, pct, secs, utcClock } from "../lib/fmt";
import { useStore } from "../state/store";

export default function Overview() {
  const health = useStore((s) => s.health);
  const incidents = useStore((s) => s.incidents);
  const timeline = useStore((s) => s.timeline);
  const [bundle, setBundle] = useState<IncidentBundle | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);
  const incidentId = incidents[0]?.id ?? "INC-4412";

  useEffect(() => {
    client.incident(incidentId).then((b) => { setBundle(b); setCursor(b.metrics.length - 1); }).catch(() => setBundle(null));
  }, [incidentId]);

  const rows = bundle?.metrics ?? [];
  const alertIdx = bundle ? markerIndex(rows, bundle.alert.created_at) : -1;
  const alertFired = timeline.some((e) => e.type === "alert_fired" && e.refs?.incident_id === incidentId);

  useEffect(() => {
    if (!playing) { if (timer.current) window.clearInterval(timer.current); timer.current = null; return; }
    setCursor(0);
    timer.current = window.setInterval(() => {
      setCursor((c) => {
        if (c + 1 >= rows.length) { setPlaying(false); return c; }
        return c + 1;
      });
    }, 100);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, rows.length]);

  useEffect(() => {
    if (playing && cursor === alertIdx && alertIdx >= 0 && !alertFired && bundle) {
      const cond = bundle.alert.triggered_conditions?.[0] as Record<string, number> | undefined;
      void client.postTimeline({
        type: "alert_fired", persona: "sre",
        title: `${bundle.alert.severity} ${incidentId} paged: authorization success ${pct(cond?.observed, 1)} against a ${pct(cond?.slo_target, 1)} SLO`,
        detail: `${bundle.alert.source} · ${bundle.alert.title}`, refs: { incident_id: incidentId },
      });
    }
  }, [cursor, playing, alertIdx, alertFired, bundle, incidentId]);

  const prod = health?.production;
  const tree = health?.working_tree;
  const r = prod?.result;
  const degraded = prod?.verdict === "degraded";
  const tone = prod?.verdict === "healthy" ? "good" : degraded ? "critical" : "neutral";
  const row = rows[cursor];
  const alertNow = cursor >= alertIdx && alertIdx >= 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Payments platform</h1>
          <div className="text-sm text-text-2">Authorization path health, computed from what <span className="mono">main</span> would run.</div>
        </div>
        {prod && <StatusPill tone={tone} pulse={degraded}>production {prod.verdict} · main@{prod.sha}</StatusPill>}
      </header>

      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="Auth success" value={pct(r?.success_rate, 1)} tone={r ? (r.success_rate >= (health?.slo.success_rate ?? 0.995) ? "good" : "critical") : "neutral"} sub={`SLO ${pct(health?.slo.success_rate, 1)}`} hero />
        <MetricTile label="p99 latency" value={secs(r?.p99_latency_seconds)} tone={r ? (r.p99_latency_seconds <= (health?.slo.p99_seconds ?? 1) ? "good" : "critical") : "neutral"} sub={`SLO ${secs(health?.slo.p99_seconds, 1)} · edge budget 8.5s`} hero />
        <MetricTile label="Fraud-model utilization" value={num(r?.utilization, 2)} unit="×" tone={r ? (r.utilization < 1 ? "good" : "critical") : "neutral"} sub={`${num(r?.offered_rps)} of ${num(r?.capacity_rps)} rps · ${num(r?.mean_attempts_per_call, 2)} attempts/call`} hero />
        <MetricTile label="Cache hit rate" value={pct(r?.cache_hit_rate, 0)} tone={r ? (r.cache_hit_rate > 0.5 ? "good" : "critical") : "neutral"} sub={prod?.config ? `TTL ${String(prod.config.CACHE_TTL_SECONDS)}s · timeout ${String(prod.config.REQUEST_TIMEOUT_SECONDS ?? "none")} · breaker ${prod.config.CIRCUIT_BREAKER_ENABLED ? "on" : "off"}` : undefined} hero />
      </div>
      {tree && tree.verdict !== prod?.verdict && (
        <div className="text-xs text-text-2">Working tree (<span className="mono">{tree.branch}</span>) would be <b>{tree.verdict}</b>: success {pct(tree.result?.success_rate, 1)}, p99 {secs(tree.result?.p99_latency_seconds)}. Production stays what <span className="mono">main</span> says until the PR is merged.</div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={<span>Incident-day telemetry · {incidentId} · {bundle ? `${utcClock(rows[0].ts)}–${utcClock(rows[rows.length - 1].ts)} UTC` : ""}</span>}
          actions={<>
            <span className="mono text-xs text-text-2">{row ? utcClock(row.ts) : ""} UTC</span>
            <Button variant="primary" persona="sre" onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Replay 13:30 → 14:40"}</Button>
          </>}>
          {bundle ? (
            <>
              <TimeSeriesChart rows={rows} markers={bundle.markers} cursor={cursor} onCursor={(i) => { if (!playing) setCursor(i); }} />
              <input type="range" min={0} max={Math.max(0, rows.length - 1)} value={cursor} onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} className="mt-2 w-full" />
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                <MetricTile label="fraud-model rps" value={num(row?.fraud_model_rps)} tone="neutral" />
                <MetricTile label="cache hit" value={pct(row?.cache_hit_rate, 0)} tone="neutral" />
                <MetricTile label="p99" value={secs(row?.p99_latency_seconds)} tone={row && row.p99_latency_seconds > 1 ? "critical" : "neutral"} />
                <MetricTile label="auth success" value={pct(row?.auth_success_rate, 1)} tone={row && row.auth_success_rate < 0.995 ? "critical" : "neutral"} />
              </div>
            </>
          ) : <div className="text-sm text-text-muted">Loading the evidence bundle…</div>}
        </Card>

        <div className="space-y-5">
          <Card tone={alertNow || alertFired ? "critical" : undefined} title="Alerting">
            {bundle ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <StatusPill tone={alertNow || alertFired ? "critical" : "good"} pulse={alertNow && !alertFired}>{alertNow || alertFired ? `${bundle.alert.severity} · ${incidentId}` : "no active alerts"}</StatusPill>
                  <span className="text-xs text-text-muted">{bundle.alert.source}</span>
                </div>
                {(alertNow || alertFired) && (
                  <>
                    <div className="font-medium">{bundle.alert.title}</div>
                    <ul className="text-xs text-text-2">
                      {bundle.alert.triggered_conditions?.map((c, i) => (
                        <li key={i}><span className="mono">{String(c.monitor)}</span>: observed <b>{c.observed !== undefined ? pct(Number(c.observed), 1) : `${String(c.observed_seconds)}s`}</b> vs {c.slo_target !== undefined ? pct(Number(c.slo_target), 1) : `${String(c.threshold_seconds)}s`} ({String(c.window)})</li>
                      ))}
                    </ul>
                    <div className="grid grid-cols-3 gap-2 text-center text-xs">
                      {Object.entries(bundle.alert.impacted ?? {}).map(([k, v]) => <div key={k} className="rounded-md bg-surface-2 p-2"><div className="text-lg font-semibold tabular">{v.toLocaleString()}</div><div className="text-text-muted">{k.replace(/_/g, " ")}</div></div>)}
                    </div>
                    <Link to={`/incidents/${incidentId}`} className="inline-block text-sm text-accent">Open {incidentId} →</Link>
                  </>
                )}
                {!alertNow && !alertFired && <div className="text-xs text-text-muted">Press replay: the page fires at {utcClock(bundle.alert.created_at)}.</div>}
              </div>
            ) : null}
          </Card>
          <Card title="Timeline" actions={<span className="text-xs text-text-muted">{timeline.length} events</span>}>
            <Timeline events={timeline} limit={8} dense />
          </Card>
        </div>
      </div>
    </div>
  );
}
