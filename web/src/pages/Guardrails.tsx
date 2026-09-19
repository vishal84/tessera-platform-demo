import { useEffect, useState } from "react";
import { client } from "../api/client";
import type { Policy } from "../api/types";
import { AuditFeed } from "../components/AuditFeed";
import { PolicyPanel } from "../components/PolicyPanel";
import { Card } from "../components/primitives";
import { useStore } from "../state/store";

export default function Guardrails() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const audit = useStore((s) => s.audit);
  useEffect(() => { client.policy().then(setPolicy).catch(() => setPolicy(null)); }, []);
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold">Guardrails</h1>
        <div className="text-sm text-text-2">Rules as code. A hook is a program with an exit code — it cannot be talked out of it, and it runs the same at 2pm with an audience and at 3am with nobody awake.</div>
      </header>
      <Card title="Policy — what is enforced, and where">{policy ? <PolicyPanel policy={policy} /> : <div className="text-sm text-text-muted">Loading…</div>}</Card>
      <Card title="Audit trail — every decision the hooks made" actions={<span className="mono text-xs text-text-muted">.tessera/audit.jsonl</span>}>
        <AuditFeed events={audit} />
      </Card>
    </div>
  );
}
