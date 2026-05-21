# Runbook: risk-gateway

**Owner:** risk-platform · **Tier:** 1 · **Pages:** yes

The risk gateway calls the fraud model on the synchronous authorization path.
Every card authorization blocks on it. It fails **closed**: no decision means
decline.

## Symptoms → first checks

| Symptom | Look at |
|---|---|
| Auth success rate dropping | `risk_gateway.fraud_model.error_rate`, then the deploy timeline |
| p99 pinned at 8.5s | Callers are exhausting the edge budget, not merely slow |
| `connection_pool_saturated` | Offered load exceeds capacity; find what raised the load |
| `fraud_model_exhausted` | Retries are being burned; check whether they are amplifying |

## The failure mode to know about

This service is prone to **metastable failure**. Retries add load at exactly
the moment the dependency has least headroom, so once offered load exceeds
capacity the system has a second, stable, bad state that it will not leave on
its own. Restarting the callers does not help; reducing offered load does.

The practical consequence: when the fraud model is slow, ask what *raised the
offered load* before you ask what made the model slow. Authorization volume
being flat does not mean the load on the model was flat — they are different
numbers, and the ratio between them is the one that moves.

```
cache misses ──▶ more load ──▶ queueing ──▶ timeouts ──▶ retries
                     ▲                                      │
                     └──────────────────────────────────────┘
```

Confirm it with the capacity model rather than guessing:

```bash
uv run python -m services.risk_gateway.simulation
```

If `utilization` is above 1.0 and `attempts` is above 2, you are in it.

## Mitigation, in order

1. **Shed load first.** Amplification has to stop before anything else helps.
2. **Work out what changed on our side before blaming the dependency.**
   Correlate the metrics inflection against `deploys.txt` and `git log`. A
   sharp inflection that lines up with a deploy is a regression until proven
   otherwise.
3. **Roll back** the deploy that lines up, if one does.
4. Only then look at the fraud model service itself.

## Known gaps

The call policy in `services/risk_gateway/config.py` has come up in review
before and has not been revisited. If you are investigating amplification,
read it against the reliability rules in `CLAUDE.md` — timeouts, backoff and
jitter, and what fails open versus closed.

## Escalation

risk-platform primary → payments-platform secondary → VP Eng for SEV-1.
Anything touching the ledger also pages the ledger owner.
