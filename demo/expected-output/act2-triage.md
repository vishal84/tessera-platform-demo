# Beat 2.2 — captured triage

`/triage-incident INC-4412`, `incident-responder` agent. Use this if live
triage stalls or runs long. The SHA below is real — `git show b745a5a`
verifies it in the room.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 11:20 | `087e524` — "perf: raise risk-gateway connection pool limit", 256 → 512 |
| 14:00 | `4b56e1d` — docstring only, no behaviour change |
| 13:30–14:02 | Steady state. ~96 rps to the fraud model, 77% cache hit rate, p99 0.54s, success ≥99.9% |
| 13:58 | `b745a5a` — "perf: reduce risk-gateway pod memory footprint" |
| 14:02:07 | risk-gateway deploys `4b56e1d`, carrying all three commits |
| 14:03 | **Inflection.** All four series break in one minute |
| 14:05:30 | First `fraud_model_exhausted` — retries burning through |
| 14:11:00 | `connection_pool_saturated`: 512 in use, 3,118 queued |
| 14:11 | Page fires — 8 minutes after impact began |

## Which of the three

All three commits shipped in the 14:02 deploy, so the deploy timestamp alone
does not identify the cause. Reading the diffs:

- `4b56e1d` is a docstring. No behaviour change. Ruled out immediately.
- `087e524` raises `MAX_CONNECTIONS` 256 → 512. Plausible — a bigger pool
  means more concurrent load on the dependency — but it cannot produce a **12x
  rise in calls to the fraud model** while authorization volume is flat. A
  pool limit caps concurrency; it does not create requests. It is a real
  contributing factor (it kept 512 doomed requests in flight rather than
  shedding them) but it is not the trigger.
- `b745a5a` disables the response cache. This is the only change that turns
  one authorization into multiple model calls.

The discriminating observation is the **ratio**, not the volume:
authorizations were flat, fraud-model RPS went 96 → 1,138.

## Root cause

Commit **`b745a5a`**, one line in `services/risk_gateway/config.py`:

```diff
-CACHE_TTL_SECONDS = 300
+CACHE_TTL_SECONDS = 0
```

The intent was memory relief: the pods sat at ~400MB and tripped the overnight
memory-pressure alert. The commit message reasons that the dependency has
latency headroom, so the change should be neutral for the auth path.

It was not, because the headroom was a product of the cache. `ops/slo.yaml`
records the fraud model at 155 rps of capacity, provisioned against observed
steady-state demand of ~96 rps. That observation was taken *with* the cache
absorbing 77% of scoring calls. Removing it puts the full ~420 auth/s onto a
155 rps dependency.

**Reproduced** with `services/risk_gateway/simulation.py`:

```
live config (ttl=0):   utilization=7.22  attempts=2.67  p99=8.50s  success=70.8%
before      (ttl=300): utilization=0.62  attempts=1.00  p99=0.54s  success=100.0%
```

Both match the telemetry. `alert.json` records observed success 0.708 and p99
8.47s.

Note the utilization is **7.2x**, not the 4x the dead cache alone explains. The
extra 1.8x is retry amplification, and that is the part that made it an
incident rather than a slowdown.

## Contributing factors

The TTL change was a 4x overload. These turned it into a 7x overload that
could not recover on its own. All are live at HEAD.

1. **`REQUEST_TIMEOUT_SECONDS = None`** — unbounded call on the synchronous
   auth path. Each attempt's patience defaults to the whole 8.5s edge budget.
   `traces.json` shows `http.timeout_seconds: null` on every span. Directly
   violates the reliability rules in `CLAUDE.md`.

2. **`RETRY_ATTEMPTS = 3`, `RETRY_BACKOFF_BASE_SECONDS = 0.0`, no jitter** —
   four attempts back to back with no delay. In `client.py` the `time.sleep`
   is guarded by `if config.RETRY_BACKOFF_BASE_SECONDS:`, so at 0.0 the
   backoff branch is dead code. This is what makes the failure **metastable**:
   retries add load exactly when the dependency has least headroom, so the
   system settles into a second stable bad state. Nothing recovers across the
   full 37 minutes after the inflection.

3. **`CIRCUIT_BREAKER_ENABLED = False`** — scaffolding present, never enabled.
   A breaker would not have restored the lost capacity, but it would have
   capped amplification at 1.0 attempts and contained the blast radius.

4. **No alert on cache hit rate.** It went 0.76 → 0.00 with authorization
   volume flat. An unambiguous leading indicator that nobody watched; the page
   came from the downstream SLO eight minutes later.

5. **No test reads the live config.** `test_capacity.py` asserts against a
   hardcoded healthy constant, so `config_from_module()` is never exercised. A
   one-line CI check against the live values would have caught this in the PR.

## Fix

Restore `CACHE_TTL_SECONDS = 300`; set `REQUEST_TIMEOUT_SECONDS = 1.0`; reduce
retries to 2 with exponential backoff and jitter; enable the circuit breaker.
Add a capacity assertion that reads the live config, and an alert on cache hit
rate.

## Open question

`ops/incidents/INC-4412/README.md` says "mitigated", but `CACHE_TTL_SECONDS` is
still 0 at HEAD and the metrics never recover inside the captured window.
Either mitigation was applied out of band or the rollback never happened —
worth confirming before the postmortem claims mitigation.

---

*This last point is worth reading out. Nobody planted it; it is a real
inconsistency between the evidence bundle and the repository state, and
noticing it is exactly the kind of thing you want from a triage pass.*
