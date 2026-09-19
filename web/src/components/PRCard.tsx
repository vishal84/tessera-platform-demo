import { useState } from "react";
import { ApiError, client } from "../api/client";
import type { PullRequest } from "../api/types";
import { clock } from "../lib/fmt";
import { CodeBlock, Markdown } from "./CodeBlock";
import { Button, Card, StatusPill } from "./primitives";

export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md border border-border bg-surface-2 p-2 text-[11px] leading-relaxed">
      {diff.split("\n").map((line, i) => {
        const tone = line.startsWith("+++") || line.startsWith("---") ? "text-text-muted"
          : line.startsWith("+") ? "text-status-good" : line.startsWith("-") ? "text-status-critical"
          : line.startsWith("@@") ? "text-accent" : "text-text-2";
        const bg = line.startsWith("+") && !line.startsWith("+++") ? "color-mix(in srgb, var(--status-good) 10%, transparent)"
          : line.startsWith("-") && !line.startsWith("---") ? "color-mix(in srgb, var(--status-critical) 10%, transparent)" : undefined;
        return <div key={i} className={tone} style={{ background: bg }}>{line || " "}</div>;
      })}
    </pre>
  );
}

export function PRCard({ pr }: { pr: PullRequest }) {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showBody, setShowBody] = useState(true);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e instanceof ApiError ? `${e.message}${Array.isArray(e.details) ? ": " + (e.details as string[]).join("; ") : ""}` : String(e)); }
    finally { setBusy(false); }
  };
  const merged = pr.state === "merged";
  const adds = pr.files.reduce((a, f) => a + f.additions, 0), dels = pr.files.reduce((a, f) => a + f.deletions, 0);

  return (
    <Card tone={merged ? "good" : "info"}
      title={<span className="flex items-center gap-2">Pull request <StatusPill tone={merged ? "good" : "info"}>{pr.state}</StatusPill><span className="text-xs font-normal text-text-muted">{pr.provider === "local" ? "local · no remote configured" : `#${pr.number}`}</span></span>}
      actions={!merged && (
        <>
          <Button persona="swe" disabled={busy} onClick={() => act(async () => setPrompt((await client.requestReview(pr.id, "swe")).prompt))}>Request review</Button>
          {!confirm
            ? <Button variant="primary" persona="swe" disabled={busy} onClick={() => setConfirm(true)}>Merge</Button>
            : <Button variant="danger" disabled={busy} onClick={() => act(async () => { await client.mergePR(pr.id, "swe"); setConfirm(false); })}>Confirm merge into {pr.base}</Button>}
        </>
      )}>
      <div className="text-base font-semibold">{pr.title}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-2">
        <span className="mono">{pr.branch}</span><span>→</span><span className="mono">{pr.base}</span>
        {pr.head_sha && <span>head <span className="mono">{pr.head_sha}</span></span>}
        {pr.created_at && <span>opened {clock(pr.created_at)}</span>}
        <span><span className="text-status-good">+{adds}</span> <span className="text-status-critical">−{dels}</span> in {pr.files.length} file{pr.files.length === 1 ? "" : "s"}</span>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Commits</div>
          <ul className="space-y-1 text-xs">
            {pr.commits.map((c) => <li key={c.sha} className="flex gap-2"><span className="mono text-text-muted">{c.short}</span><span className="min-w-0 truncate">{c.subject}</span><span className="ml-auto shrink-0 text-text-muted">{c.author}</span></li>)}
            {!pr.commits.length && <li className="text-text-muted">no commits ahead of {pr.base}</li>}
          </ul>
        </div>
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Files</div>
          <ul className="space-y-1 text-xs">
            {pr.files.map((f) => <li key={f.path} className="flex gap-2"><span className="mono min-w-0 truncate">{f.path}</span><span className="ml-auto shrink-0"><span className="text-status-good">+{f.additions}</span> <span className="text-status-critical">−{f.deletions}</span></span></li>)}
          </ul>
          <button className="mt-1 text-xs text-accent" onClick={() => act(async () => setDiff(diff === null ? (await client.prDiff(pr.id)).diff : null))}>{diff === null ? "show diff" : "hide diff"}</button>
        </div>
      </div>
      {diff !== null && <div className="mt-3"><DiffView diff={diff} /></div>}

      {prompt && (
        <div className="mt-3 rounded-md border p-3" style={{ borderColor: "color-mix(in srgb, var(--persona-swe) 50%, var(--color-border))" }}>
          <div className="mb-1 text-xs font-semibold">Hand-off → SWE. In the Claude Code desktop app, type:</div>
          <CodeBlock wrap code={prompt} />
        </div>
      )}
      {error && <div className="mt-3 text-sm text-status-critical">{error}</div>}

      <div className="mt-3 border-t border-border pt-2">
        <button className="text-xs text-accent" onClick={() => setShowBody((s) => !s)}>{showBody ? "hide description" : "show description"}</button>
        {showBody && <div className="mt-1 max-h-96 overflow-auto"><Markdown text={pr.body_md || "_no description_"} /></div>}
      </div>
    </Card>
  );
}
