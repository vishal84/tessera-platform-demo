import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, client } from "../api/client";
import type { GateEvent, Registry, RunContract, ShadowReport } from "../api/types";
import { ActivityFeed } from "../components/ActivityFeed";
import { CodeBlock } from "../components/CodeBlock";
import { GateCard } from "../components/GateCard";
import { PhaseStepper } from "../components/PhaseStepper";
import { PRCard } from "../components/PRCard";
import { RunControls } from "../components/RunControls";
import { Button, Card, Empty, MetricTile, StatusPill } from "../components/primitives";
import { Timeline } from "../components/Timeline";
import { pct } from "../lib/fmt";
import { actions, useStore } from "../state/store";

const GATES = [
  { key: "leakage", title: "Gate 1 · point-in-time correctness", description: "No feature may use information unavailable at scoring time." },
  { key: "performance", title: "Gate 2 · performance floor", description: "PR-AUC against a recorded floor on a temporal split." },
  { key: "drift", title: "Gate 3 · drift", description: "PSI between the training distribution and recent traffic." },
  { key: "fairness", title: "Gate 4 · fairness slices", description: "Reported per slice, never in aggregate." },
  { key: "model_card", title: "Model card", description: "MRM will not review a model without one." },
] as const;

const NO_GATES: GateEvent[] = [];
const PROMPT_LABELS = ["Prompt 1 · investigate", "Prompt 2 · productionize"];

export default function Models() {
  const { name = "fraud-v3-candidate" } = useParams();
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [shadow, setShadow] = useState<ShadowReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notebook, setNotebook] = useState<{ url: string; exists: boolean; jupyter_reachable: boolean; path: string } | null>(null);
  const [proof, setProof] = useState<{ exit_code: number; tests: Array<{ name: string; outcome: string }>; output: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState<number | null>(null);
  const [contract, setContract] = useState<RunContract | null>(null);
  const [now, setNow] = useState(Date.now());
  const gates = useStore((s) => s.gates[name]) ?? NO_GATES;
  const timeline = useStore((s) => s.timeline);
  const run = useStore((s) => s.activeRun);
  const activity = useStore((s) => s.activity);
  const recordings = useStore((s) => s.recordings);
  const prs = useStore((s) => s.prs);
  const myRun = run && run.track === "model" && run.subject_id === name ? run : null;
  const myPRs = prs.filter((p) => p.track === "model");

  const load = () => {
    setError(null);
    Promise.all([client.models(), client.shadow(name), client.notebookUrl(name), actions.refreshGates(name)])
      .then(([r, s, n]) => { setRegistry(r); setShadow(s); setNotebook(n); })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
    client.modelContract(name).then(setContract).catch(() => setContract(null));
  };
  useEffect(load, [name]);
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);

  const openNotebook = async () => {
    if (!notebook) return;
    window.open(notebook.url, "_blank", "noopener");
    await client.postTimeline({ type: "notebook_opened", persona: "ds", title: `Opened ${notebook.path} in JupyterLab`, refs: { model: name, path: notebook.path } });
  };
  const runGates = async () => { setBusy(true); try { await client.runGates(name); } finally { setBusy(false); } };
  const runProof = async () => { setBusy(true); try { setProof(await client.proof(name)); } finally { setBusy(false); } };

  const candidate = registry?.candidates.find((c) => c.name === name);
  const gap = shadow ? shadow.offline.auc - shadow.shadow.auc : 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Model registry · fraud</h1>
          <div className="text-sm text-text-2">Champion vs candidate, the shadow run that stopped the promotion, and the four gates every model PR must clear.</div>
        </div>
        {registry && <span className="mono text-xs text-text-muted">{registry.from}</span>}
      </header>

      {error && <Empty>{error} — run <span className="mono">./demo/reset-demo.sh</span> to regenerate the registry.</Empty>}

      {shadow && candidate && (
        <div className="grid gap-3 md:grid-cols-4">
          <MetricTile label={`${registry?.champion?.name ?? "champion"} · in production`} value={shadow.champion_same_window.auc.toFixed(3)} unit="AUC" tone="good" sub={`PR-AUC ${shadow.champion_same_window.pr_auc.toFixed(3)} on the shadow window`} hero />
          <MetricTile label={`${name} · offline`} value={shadow.offline.auc.toFixed(3)} unit="AUC" tone="info" sub={`PR-AUC ${shadow.offline.pr_auc.toFixed(3)} · ${shadow.offline.source}`} hero />
          <MetricTile label={`${name} · shadow`} value={shadow.shadow.auc.toFixed(3)} unit="AUC" tone="critical" sub={`PR-AUC ${shadow.shadow.pr_auc.toFixed(3)} · ${shadow.window.scored_transactions.toLocaleString()} scored`} hero />
          <MetricTile label="Offline → shadow gap" value={`−${gap.toFixed(3)}`} tone="critical" sub={shadow.reason} hero />
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={`Shadow report · ${name}`} actions={shadow && <StatusPill tone="critical">{shadow.status} · {shadow.ticket}</StatusPill>}>
          {shadow ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">By month, shadow AUC</div>
                <div className="space-y-1">
                  {shadow.shadow.by_month.map((m) => (
                    <div key={m.month} className="flex items-center gap-2 text-xs"><span className="mono w-16">{m.month}</span>
                      <div className="h-3 flex-1 rounded-sm bg-surface-2"><div className="h-3 rounded-sm" style={{ width: `${m.auc * 100}%`, background: "var(--series-3)" }} /></div>
                      <span className="mono w-12 text-right">{m.auc.toFixed(3)}</span><span className="w-14 text-text-muted">n={m.n.toLocaleString()}</span></div>
                  ))}
                  <div className="flex items-center gap-2 text-xs"><span className="mono w-16">champion</span>
                    <div className="h-3 flex-1 rounded-sm bg-surface-2"><div className="h-3 rounded-sm" style={{ width: `${shadow.champion_same_window.auc * 100}%`, background: "var(--status-good)" }} /></div>
                    <span className="mono w-12 text-right">{shadow.champion_same_window.auc.toFixed(3)}</span><span className="w-14" /></div>
                </div>
                <div className="mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Window</div>
                <div className="text-xs text-text-2">{shadow.window.start} → {shadow.window.end} · {shadow.window.labels}</div>
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Feature stats, training vs scoring</div>
                {Object.entries(shadow.feature_stats).map(([f, s]) => (
                  <div key={f} className="rounded-md border border-border p-2 text-xs">
                    <div className="mono font-semibold">{f}</div>
                    <div className="mt-1 grid grid-cols-2 gap-2">
                      <div><div className="text-text-muted">non-zero in training</div><div className="text-lg font-semibold tabular">{pct(s.training_nonzero_share, 1)}</div></div>
                      <div><div className="text-text-muted">non-zero at scoring</div><div className="text-lg font-semibold tabular text-status-critical">{pct(s.shadow_nonzero_share, 1)}</div></div>
                    </div>
                    <div className="mt-1 text-text-2">served from <span className="mono">{shadow.feature_serving[f]?.source}</span> — {shadow.feature_serving[f]?.computed_from}</div>
                  </div>
                ))}
                <div className="mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Features</div>
                <div className="flex flex-wrap gap-1">{shadow.features.map((f) => <span key={f} className="mono rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11px]">{f}</span>)}</div>
              </div>
            </div>
          ) : <div className="text-sm text-text-muted">No shadow report.</div>}
        </Card>

        <Card title="Investigate" actions={<StatusPill tone={notebook?.jupyter_reachable ? "good" : "warning"}>{notebook?.jupyter_reachable ? "JupyterLab up" : "JupyterLab not reachable"}</StatusPill>}>
          <div className="space-y-3 text-sm">
            <div className="text-text-2">The number that stopped the promotion came from the console. The explanation comes from the notebook.</div>
            <Button variant="primary" persona="ds" disabled={!notebook?.exists} onClick={openNotebook}>Open investigation notebook</Button>
            <div className="mono text-[11px] text-text-muted">{notebook?.path}</div>
            <div className="flex flex-wrap gap-2">
              {(contract?.prompt_parts ?? []).map((_, i) => (
                <Button key={i} onClick={() => setPrompt(prompt === i ? null : i)}>{PROMPT_LABELS[i] ?? `Prompt ${i + 1}`}</Button>
              ))}
            </div>
            {prompt !== null && contract?.prompt_parts[prompt] && (
              <CodeBlock wrap label="type this in the desktop app, as the data scientist" code={contract.prompt_parts[prompt]} />
            )}
            {contract && (
              <div className="text-[11px] text-text-muted">
                Read from <span className="mono">{contract.source}</span> — the same text the unattended run uses.
              </div>
            )}
          </div>
        </Card>
      </div>

      <Card title="Investigation run"
        actions={<span className="text-xs text-text-muted">{myRun ? `${activity.filter((e) => e.type === "tool_call").length} tool calls` : "no run"}</span>}>
        <div className="space-y-4">
          <RunControls subjectId={name} run={myRun} recordings={recordings} track="model" persona="ds"
            liveLabel="Investigate with Claude" />
          <PhaseStepper run={myRun} activity={myRun ? activity : []} now={now} track="model" />
          <div className="h-[24rem]">
            <ActivityFeed events={myRun ? activity : []} startedAt={myRun?.started_at} running={myRun?.status === "running"} />
          </div>
        </div>
      </Card>

      {myPRs.map((pr) => <PRCard key={pr.id} pr={pr} />)}

      <Card title="Validation gates — the contract in .github/workflows/model-validation.yml"
        actions={<>
          {registry && <StatusPill tone={registry.validation_present ? "good" : "warning"}>{registry.validation_present ? "ml/validation implemented" : "ml/validation missing · TESS-2310"}</StatusPill>}
          <Button variant="primary" persona="ds" disabled={busy} onClick={runGates}>Run validation gates</Button>
          <Button disabled={busy || !registry?.validation_present} onClick={runProof} title="uv run pytest ml/validation">Negative proof</Button>
        </>}>
        <div className="grid gap-3 md:grid-cols-5">
          {GATES.map((g) => <GateCard key={g.key} title={g.title} description={g.description} gate={gates.find((x) => x.gate === g.key)} />)}
        </div>
        {proof && (
          <div className="mt-4 rounded-md border border-border p-3 text-xs">
            <div className="mb-1 flex items-center gap-2 font-semibold">Negative proof <StatusPill tone={proof.exit_code === 0 ? "good" : "critical"}>pytest exit {proof.exit_code}</StatusPill></div>
            <ul className="space-y-0.5">{proof.tests.map((t) => <li key={t.name} className="flex gap-2"><StatusPill tone={t.outcome === "passed" ? "good" : "critical"}>{t.outcome}</StatusPill><span className="mono">{t.name}</span></li>)}</ul>
            {!proof.tests.length && <pre className="max-h-40 overflow-auto text-text-2">{proof.output}</pre>}
          </div>
        )}
      </Card>

      <Card title="Timeline"><Timeline events={timeline.filter((e) => e.persona === "ds" || e.refs?.model === name || e.refs?.track === "model" || ["gates_run", "gate_passed", "gate_blocked", "gates_implemented", "model_card_added", "aggregates_added", "notebook_updated"].includes(e.type))} limit={12} dense /></Card>
    </div>
  );
}
