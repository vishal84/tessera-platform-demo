import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Marker, MetricRow } from "../api/types";
import { utcClock } from "../lib/fmt";

interface Panel {
  key: keyof Omit<MetricRow, "ts">;
  label: string;
  color: string;
  domain: (rows: MetricRow[]) => [number, number];
  fmt: (v: number) => string;
  slo?: number;
}

const PANELS: Panel[] = [
  { key: "fraud_model_rps", label: "fraud-model requests / s", color: "var(--series-1)", domain: (r) => [0, Math.max(...r.map((x) => x.fraud_model_rps)) * 1.08], fmt: (v) => v.toFixed(0) },
  { key: "cache_hit_rate", label: "cache hit rate", color: "var(--series-2)", domain: () => [0, 1], fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "p99_latency_seconds", label: "p99 latency (s)", color: "var(--series-3)", domain: (r) => [0, Math.max(1.2, ...r.map((x) => x.p99_latency_seconds)) * 1.08], fmt: (v) => `${v.toFixed(2)}s`, slo: 1.0 },
  { key: "auth_success_rate", label: "authorization success", color: "var(--series-4)", domain: () => [0.6, 1.0], fmt: (v) => `${(v * 100).toFixed(1)}%`, slo: 0.995 },
];

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(800);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    setWidth(ref.current.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function markerIndex(rows: MetricRow[], ts: string): number {
  const i = rows.findIndex((r) => r.ts >= ts);
  return i === -1 ? rows.length - 1 : i;
}

export function TimeSeriesChart({ rows, markers, cursor, onCursor, panelHeight = 88 }:
  { rows: MetricRow[]; markers: Marker[]; cursor: number; onCursor: (i: number) => void; panelHeight?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const left = 52, right = 12, gap = 14, axisH = 22;
  const plotW = Math.max(60, width - left - right);
  const n = rows.length;
  const x = (i: number) => left + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const topPad = 12;
  const height = PANELS.length * (panelHeight + gap) + axisH + topPad;
  const markerXs = useMemo(() => markers.map((m) => ({ ...m, i: markerIndex(rows, m.ts) })), [rows, markers]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left - left;
    const i = Math.round((px / plotW) * (n - 1));
    onCursor(Math.max(0, Math.min(n - 1, i)));
  };

  const ticks = rows.map((r, i) => ({ i, label: utcClock(r.ts) })).filter((t) => t.label.endsWith("0"));

  return (
    <div ref={ref} className="w-full select-none">
      <svg width={width} height={height} onMouseMove={onMove} className="block" style={{ fontFamily: "var(--font-mono)" }}>
        {PANELS.map((panel, p) => {
          const top = topPad + p * (panelHeight + gap);
          const [lo, hi] = panel.domain(rows);
          const y = (v: number) => top + panelHeight - ((v - lo) / (hi - lo)) * panelHeight;
          const path = rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(r[panel.key]).toFixed(1)}`).join(" ");
          const area = `${path} L${x(n - 1).toFixed(1)},${(top + panelHeight).toFixed(1)} L${x(0).toFixed(1)},${(top + panelHeight).toFixed(1)} Z`;
          const value = rows[cursor]?.[panel.key];
          return (
            <g key={panel.key}>
              <rect x={left} y={top} width={plotW} height={panelHeight} fill="none" stroke="var(--chart-grid)" />
              {[0.5].map((f) => <line key={f} x1={left} x2={left + plotW} y1={top + panelHeight * f} y2={top + panelHeight * f} stroke="var(--chart-grid)" strokeDasharray="2 4" />)}
              {panel.slo !== undefined && panel.slo >= lo && panel.slo <= hi && (
                <g>
                  <line x1={left} x2={left + plotW} y1={y(panel.slo)} y2={y(panel.slo)} stroke="var(--status-critical)" strokeDasharray="4 4" opacity={0.7} />
                  <text x={left + plotW - 4} y={y(panel.slo) - 3} fontSize={10} textAnchor="end" fill="var(--status-critical)">SLO {panel.fmt(panel.slo)}</text>
                </g>
              )}
              <path d={area} fill={panel.color} opacity={0.08} />
              <path d={path} fill="none" stroke={panel.color} strokeWidth={2} strokeLinejoin="round" />
              <text x={4} y={top + 11} fontSize={10} fill="var(--color-text-muted)">{panel.label}</text>
              <text x={4} y={top + panelHeight - 2} fontSize={10} fill="var(--chart-axis)">{panel.fmt(lo)}</text>
              <text x={4} y={top + 24} fontSize={10} fill="var(--chart-axis)">{panel.fmt(hi)}</text>
              {markerXs.map((m, k) => (
                <line key={k} x1={x(m.i)} x2={x(m.i)} y1={top} y2={top + panelHeight}
                  stroke={m.kind === "alert" ? "var(--chart-marker-alert)" : m.kind === "inflection" ? "var(--series-3)" : "var(--chart-marker-deploy)"}
                  strokeDasharray={m.kind === "deploy" ? "3 3" : m.kind === "inflection" ? "1 3" : undefined} opacity={m.kind === "alert" ? 0.9 : 0.6} />
              ))}
              {value !== undefined && (
                <g>
                  <circle cx={x(cursor)} cy={y(value)} r={3.5} fill={panel.color} stroke="var(--color-surface)" strokeWidth={1.5} />
                  <text x={Math.min(x(cursor) + 6, left + plotW - 40)} y={y(value) - 6} fontSize={11} fontWeight={600} fill="var(--color-text)">{panel.fmt(value)}</text>
                </g>
              )}
            </g>
          );
        })}
        {/* cursor */}
        <line x1={x(cursor)} x2={x(cursor)} y1={topPad} y2={height - axisH} stroke="var(--chart-cursor)" strokeWidth={1} opacity={0.5} />
        {/* marker labels: deploys above the first panel (service name only), alert and inflection below the axis */}
        {markerXs.filter((m) => m.kind === "deploy").map((m, k) => (
          <text key={`d${k}`} x={x(m.i)} y={topPad - 3} fontSize={9} textAnchor="middle" fill="var(--color-text-muted)">▲ {m.label.split(" ")[0]}</text>
        ))}
        {markerXs.filter((m) => m.kind !== "deploy").map((m, k) => (
          <g key={`a${k}`}>
            {m.kind === "alert" && <circle cx={x(m.i)} cy={height - 6} r={3.5} fill="var(--chart-marker-alert)" />}
            <text x={x(m.i) + (m.kind === "alert" ? 7 : 0)} y={height - 2} fontSize={9} textAnchor={m.kind === "alert" ? "start" : "end"}
              fill={m.kind === "alert" ? "var(--chart-marker-alert)" : "var(--series-3)"}>
              {m.kind === "alert" ? m.label : "inflection"}
            </text>
          </g>
        ))}
        {ticks.map((t) => (
          <text key={t.i} x={x(t.i)} y={height - axisH + 12} fontSize={10} textAnchor="middle" fill="var(--chart-axis)">{t.label}</text>
        ))}
      </svg>
    </div>
  );
}
