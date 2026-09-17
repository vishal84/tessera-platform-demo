# INC-4412 — Authorization success rate breach

**2026-09-17 · SEV-2 · risk-gateway · status: mitigated, root cause open**

Authorization success rate fell from ~99.9% to ~71% and p99 latency on the
fraud model call went from ~0.54s to the 8.5s edge budget. Roughly 41,300
authorizations were declined that should have been approved, across 2,184
merchants.

## Evidence in this bundle

| File | What it holds |
|---|---|
| `alert.json` | The paging alert, with observed values and SLO targets |
| `metrics.csv` | 70 minutes at 1-minute resolution, spanning the inflection |
| `logs.jsonl` | Structured risk-gateway logs from before and during |
| `traces.json` | One representative slow authorization, span by span |
| `deploys.txt` | Every deploy that day, with times and revisions |

## What is known

Authorization success rate and fraud-model latency both degraded sharply and
did not recover on their own. Traffic to the payments API was within its
normal range throughout.

## What is not known

Root cause. That is the exercise.

> Start with `/triage-incident INC-4412`.

Useful context lives in `ops/runbooks/risk-gateway.md` and `ops/slo.yaml`. The
capacity model in `services/risk_gateway/simulation.py` will reproduce whatever
hypothesis you land on, which is a faster way to test one than arguing about it.
