import type { Policy } from "../api/types";
import { StatusPill } from "./primitives";

export function PolicyPanel({ policy }: { policy: Policy }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Deny — .claude/settings.json</div>
        <ul className="space-y-0.5 text-xs">{policy.deny.map((d) => <li key={d} className="mono rounded-sm bg-surface-2 px-1.5 py-0.5">{d}</li>)}</ul>
        <div className="mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Allow without prompting</div>
        <ul className="flex flex-wrap gap-1 text-[11px]">{policy.allow.map((a) => <li key={a} className="mono rounded-sm border border-border px-1.5 py-0.5 text-text-2">{a}</li>)}</ul>
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Hooks — deterministic, exit code 2 blocks</div>
        <ul className="space-y-1.5 text-xs">
          {policy.hooks.map((h, i) => (
            <li key={i} className="rounded-md border border-border p-2">
              <div className="flex items-center gap-2"><span className="font-semibold">{h.event}</span><span className="mono text-text-muted">{h.matcher}</span></div>
              <div className="mono mt-0.5 truncate text-text-2" title={h.command ?? ""}>{h.command}</div>
            </li>
          ))}
        </ul>
        <div className="mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Selftests (run just now)</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {Object.entries(policy.selftests).map(([name, r]) => (
            <StatusPill key={name} tone={r.failed === 0 && r.exit_code === 0 ? "good" : "critical"}>{name}: {r.passed ?? "?"} passed{r.failed ? `, ${r.failed} failed` : ""}</StatusPill>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">The same checks at the door — GitHub Actions</div>
        <ul className="space-y-1.5 text-xs">
          {policy.ci_mirror.map((s, i) => (
            <li key={i} className="rounded-md border border-border p-2">
              <div className="flex items-center gap-2"><span className="mono text-text-muted">{s.workflow}</span><span className="font-semibold">{s.step ?? s.job}</span></div>
              <div className="mono mt-0.5 truncate text-text-2" title={s.command}>{s.command}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
