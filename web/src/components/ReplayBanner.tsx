import { client } from "../api/client";
import type { RunMeta } from "../api/types";

export function ReplayBanner({ run }: { run: RunMeta }) {
  const speeds = [1, 4, 8, 16];
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-6 py-2 text-sm font-semibold uppercase tracking-[0.2em]"
      style={{ background: "var(--status-critical)", color: "#fff" }}>
      <div className="flex min-w-0 items-center gap-3">
        <span className="pulse inline-block h-3 w-3 shrink-0 rounded-full bg-white" />
        Recording · {run.speed}× — playing <span className="mono normal-case tracking-normal">{run.recording}</span>. Nothing on this screen is being generated live.
      </div>
      <div className="flex items-center gap-1 text-xs normal-case tracking-normal">
        {speeds.map((s) => (
          <button key={s} onClick={() => client.setSpeed(run.run_id, s)}
            className={`rounded-sm border border-white/40 px-2 py-0.5 ${run.speed === s ? "bg-white/25" : "hover:bg-white/15"}`}>{s}×</button>
        ))}
      </div>
    </div>
  );
}
