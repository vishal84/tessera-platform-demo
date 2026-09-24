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

## A deploy record names a revision, not a payload

Learned in INC-4412, and the thing most likely to cost you twenty minutes.

`deploys.txt` records the revision a rollout landed on. That rollout carries
**every commit not yet deployed**, which is usually more than one. In INC-4412
the record said `4b56e1d`, and `git show 4b56e1d` is a single docstring line —
so the deploy looked innocent. The change that caused the incident was
`b745a5a`, two commits earlier in the same rollout.

Correlate against the range, never the named revision:

```bash
git log --oneline <last-deployed-revision>..<revision-in-deploys.txt>
```

Read every diff in that range, and sort by blast radius rather than by commit
message. A `perf:` one-liner in `config.py` outranks a `feat:` in a handler.

## The cache is capacity, not an optimisation

`CACHE_TTL_SECONDS` in `services/risk_gateway/config.py` absorbs ~77% of
scoring calls. The `capacity_rps: 155` in `ops/slo.yaml` is demand measured
*after* that cache; unique demand is ~420 rps. So losing the cache is not a
latency regression, it is an instant 2.7x overload — before retries.

Nothing in the shape of the metrics will tell you the cache was *turned off*
rather than getting *less effective*: dashboard smoothing renders an
instantaneous step to zero as a smooth ten-minute decay. Check the config, not
the curve.

## Reading the traces

Per-attempt span duration is not the dependency being slow. Split it:

- `queue.wait_ms` high, `duration_ms - queue.wait_ms` ≈ 45ms → the model is
  **queued**, not slow. You have an offered-load problem, and the fix is on
  our side.
- Service time itself elevated → now it is worth looking at the fraud model.

In INC-4412 every attempt was ~2120ms of which ~2080ms was queue wait. The
dependency was healthy throughout and was a victim of our retry volume.

## Known gaps

- **The circuit breaker does not exist.** `CIRCUIT_BREAKER_ENABLED` in
  `config.py` is read by `simulation.py` and the ops console **but not by
  `client.py`**. Turning it on during an incident will make the health tile
  and the capacity model go green and change nothing about production. Do not
  reach for it as a mitigation. Implementing it is tracked in the INC-4412
  postmortem.
- **`MAX_CONNECTIONS` is not load shedding.** At 45ms service time the
  dependency saturates around 7 concurrent calls; the pool limit is two orders
  of magnitude above that. Raising it to stop pool-wait warnings removes a
  bound without adding capacity — pool-wait warnings mean the dependency is
  near saturation, so treat them as a demand signal, not a pool-sizing one.
- **A failed authorization is not idempotent.** `services/payments_api/service.py`
  does not persist a result against the idempotency key when the fraud model
  is unavailable, so merchant retries re-enter the amplifier at full cost.
  Tracked in the INC-4412 postmortem.

If you are investigating amplification, read `config.py` against the
reliability rules in `CLAUDE.md` — timeouts, backoff and jitter, and what
fails open versus closed. `services/risk_gateway/tests/test_inc_4412_regression.py`
now asserts the shipped config survives; if that suite is red, the config in
the working tree would page someone.

## Escalation

risk-platform primary → payments-platform secondary → VP Eng for SEV-1.
Anything touching the ledger also pages the ledger owner.
