# tessera-platform

Card issuing and payments platform. PCI-DSS Level 1, SOC 2 Type II.

```
services/payments_api/   HTTP edge: authorize, capture, refund, void
services/ledger/         Double-entry core. Source of truth for money.
services/risk_gateway/   Fraud model client. On the synchronous auth path.
services/console/        Ops console API: incident triage, PRs, guardrail audit trail
web/                     Ops console UI (served from web/dist by services/console)
ml/                      Fraud, credit and behaviour models; ml/registry/ holds shadow runs
ops/                     SLOs, runbooks, incident evidence
.claude/                 Guardrails, subagents, skills and commands
```

## Getting started

```bash
uv sync
uv run pytest
```

## Ops console

```bash
./demo/up.sh            # console on :8765, JupyterLab on :8888
```

The console shows gateway health computed from `main`, replays incident-day
telemetry, runs `/triage-incident` headless with the same flags as
`.github/workflows/claude-incident-fix.yml`, tracks the resulting PR, tails
the guardrail audit trail (`.tessera/audit.jsonl`, written by the hooks) and
runs the model-validation gates from `model-validation.yml` locally.

Read `CLAUDE.md` before your first change — the money and security rules there
are enforced, not advisory.

## Guardrails

`.claude/hooks/` holds two hooks that run on every file operation, in local
sessions and in CI alike:

- `protect_secrets.py` blocks reads and writes to `.env`, key material and
  `infra/prod/`, including via shell commands.
- `pii_scan.py` flags cardholder data in source, tests and log statements.

Verify them yourself:

```bash
python3 .claude/hooks/protect_secrets.py --selftest
python3 .claude/hooks/pii_scan.py --selftest
```

---

<sub>**Presenting this?** Start at [`demo/DEMO_RUNBOOK.md`](demo/DEMO_RUNBOOK.md).
This is a fictional company built for demonstration. All data is synthetic.</sub>
