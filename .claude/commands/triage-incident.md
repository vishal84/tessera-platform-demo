---
description: Triage a production incident end to end — evidence, root cause, fix, regression test, PR
argument-hint: <incident-id, e.g. INC-4412>
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
---

Triage incident **$1**.

Use the `incident-responder` agent. Work from evidence, not from memory of
similar incidents.

## 1. Read the evidence bundle

Everything in `ops/incidents/$1/`. Read all of it before forming a hypothesis:

- `alert.json` — what paged, with observed values against SLO targets
- `metrics.csv` — the time series spanning the inflection
- `logs.jsonl` — structured service logs from before and during
- `traces.json` — a representative slow request, span by span
- `deploys.txt` — everything deployed that day

Also read `ops/slo.yaml` and the relevant runbook in `ops/runbooks/`.

## 2. Find the inflection

Identify the exact minute the metrics change. Then find what else happened at
that minute. Correlate `deploys.txt` against `git log` and read the diff of
any revision that lines up.

State what the data shows before you state what you think it means.

## 3. Form and prove a hypothesis

Where the mechanism can be reproduced, reproduce it:

```bash
uv run python -m services.risk_gateway.simulation
```

Do not stop at the trigger. Ask what latent weakness let a routine change
become an incident — that is usually the more important finding.

## 4. Fix it

Address the root cause and the contributing factors that are cheap to close.
Keep the fix minimal and readable; a reviewer may be reading it under
pressure.

## 5. Write the regression test

A test that **fails before your fix and passes after**. Verify both directions
— stash the fix, watch it fail, restore it, watch it pass. An incident without
a regression test is an incident that recurs.

## 6. Update the runbook

`ops/runbooks/` — what the next responder needs to know that you just learned.

## 7. Open a PR

Branch `incident/$1-<short-slug>`. Include a postmortem draft in the
description using the `incident-postmortem` skill.

**Do not push to `main` and do not deploy.** The output of this command is a
pull request for a human to review.
