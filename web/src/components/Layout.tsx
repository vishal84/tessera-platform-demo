import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useStore } from "../state/store";
import { PersonaChip } from "./primitives";
import { ReplayBanner } from "./ReplayBanner";

const NAV = [
  { to: "/", label: "Overview", hint: "health & telemetry" },
  { to: "/incidents/INC-4412", label: "Incidents", hint: "INC-4412" },
  { to: "/guardrails", label: "Guardrails", hint: "hooks & audit" },
  { to: "/models/fraud-v3-candidate", label: "Models", hint: "fraud registry" },
];

function useTheme() {
  const [theme, setTheme] = useState<string>(() => document.documentElement.getAttribute("data-theme") ?? "dark");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("tessera.theme", theme); } catch { /* private mode */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))] as const;
}

export function Layout({ children }: { children: ReactNode }) {
  const connected = useStore((s) => s.connected);
  const health = useStore((s) => s.health);
  const activeRun = useStore((s) => s.activeRun);
  const [theme, toggle] = useTheme();
  const prod = health?.production.verdict ?? "unknown";
  const dot = prod === "healthy" ? "var(--status-good)" : prod === "degraded" ? "var(--status-critical)" : "var(--status-neutral)";

  return (
    <div className="flex h-full min-h-screen bg-bg text-text">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-muted">Tessera Financial</div>
          <div className="mt-0.5 text-base font-semibold">Ops Console</div>
        </div>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}
              className={({ isActive }) => `rounded-md px-3 py-2 text-sm ${isActive ? "bg-surface-2 font-semibold text-text" : "text-text-2 hover:bg-surface-2"}`}>
              <div>{item.label}</div>
              <div className="text-[11px] text-text-muted">{item.hint}</div>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-3 border-t border-border p-4 text-xs">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Personas</div>
            <div className="flex flex-wrap gap-1"><PersonaChip persona="sre" small /><PersonaChip persona="swe" small /><PersonaChip persona="ds" small /><PersonaChip persona="claude" small /></div>
          </div>
          <div className="flex items-center gap-2 text-text-2">
            <span className="h-2 w-2 rounded-full" style={{ background: dot }} />
            production {prod}{health?.production.sha ? <span className="mono text-text-muted">@{health.production.sha}</span> : null}
          </div>
          <div className="flex items-center gap-2 text-text-2">
            <span className={`h-2 w-2 rounded-full ${connected ? "" : "pulse"}`} style={{ background: connected ? "var(--status-good)" : "var(--status-warning)" }} />
            {connected ? "live stream connected" : "reconnecting…"}
          </div>
          <button onClick={toggle} className="w-full rounded-md border border-border px-2 py-1 text-text-2 hover:bg-surface-2">
            {theme === "dark" ? "Switch to light" : "Switch to dark"}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {activeRun?.replayed && (activeRun.status === "running" || activeRun.status === "cancelling") && <ReplayBanner run={activeRun} />}
        <main className="min-w-0 flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
