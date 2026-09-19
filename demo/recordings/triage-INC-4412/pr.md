---
title: "fix(risk): restore the fraud-model cache TTL and bound the call policy"
branch: incident/INC-4412-cache-ttl-amplification
base: main
---

## Summary

`CACHE_TTL_SECONDS` was set to `0` in `b745a5a`, which shipped in the 14:02 UTC
risk-gateway rollout on 2026-09-17. The fraud-model response cache was absorbing
about 77% of scoring calls, so disabling it put the full ~420 rps of
authorization demand onto a dependency provisioned for ~155 rps; retries without
backoff amplified that to ~1120 rps and the system settled into a metastable
overload it could not leave. Authorization success sat at 70.8% for at least 38
minutes, declining roughly 41,300 authorizations across 2,184 merchants.

This PR restores the TTL, closes the contributing factors that are cheap and
safe to close, and adds the regression test that was missing.

---

## What the evidence shows

**The metrics are a step function, not a degradation.** At `14:02:00` the
gateway logs `{"event":"config_reloaded","revision":"4b56e1d"}`. One minute
later every series moves at once:

| | 13:30–14:02 (33 samples) | 14:15–14:40 (26 samples) |
|---|---|---|
| fraud_model_rps | 96.5 | 1117.3 |
| cache_hit_rate | 0.773 | 0.000 |
| p99_latency_seconds | 0.542 | 8.503 |
| auth_success_rate | 0.998 | 0.708 |

The apparent 15-minute "decay" in `cache_hit_rate` is dashboard smoothing
applied to an instantaneous drop — a cache that genuinely got *less effective*
would not converge on exactly zero, and `_ResponseCache` has no eviction path
that could misbehave gradually. The cache did not degrade; it stopped existing
at one minute.

**The dependency was healthy the whole time.** In `traces.json`, each of the
four attempts is ~2120ms of which ~2080ms is `queue.wait_ms` — 40ms of actual
service time, against the 45ms the capacity model assumes. The fraud model was
queued, not slow. Every error string is caller-side: `"read timeout: no timeout
configured, edge budget exhausted"`.

**The deploy record points at the wrong commit.** `deploys.txt` records the
14:02 rollout as `4b56e1d`, which is a single docstring line and functionally
inert. A rollout carries every commit not yet deployed, and this one carried
three:

| commit | time | change |
|---|---|---|
| `087e524` | 11:20 | `MAX_CONNECTIONS` 256 → 512 |
| **`b745a5a`** | **13:58** | **`CACHE_TTL_SECONDS` 300 → 0** |
| `4b56e1d` | 14:00 | docstring only *(the named revision)* |

**The capacity model reproduces both states from the live config.** Run against
`config.py` as it stood:

```
live config : offered= 1122.6 rps  capacity= 155.6 rps  utilization= 7.22  cache_hit=  0%  attempts=2.67  p99=  8.50s  success=70.8%
```

That `success=70.8%` is the `0.708` in `alert.json`, and `p99=8.50s` is the
8.47s that paged. Against this PR's config:

```
live config : offered=   96.2 rps  capacity= 155.6 rps  utilization= 0.62  cache_hit= 77%  attempts=1.00  p99=  0.54s  success=100.0%
```

Which is the observed pre-incident baseline on every axis.

---

## Ruled out

- **Traffic spike.** `fraud_model_rps` is post-cache calls, not authorization
  volume. The model reproduces both the 96 rps and 1122 rps states holding
  authorizations flat at 420/s.
- **A fraud-model regression.** No fraud-model deploy that day; span timings
  show 40ms service time under 2080ms of queueing.
- **The other three deploys.** payments-api (13:04) and kyc-adapter (13:41)
  precede the inflection by 55 and 20 minutes with 33 flat samples between;
  merchant-portal (14:19) lands mid-plateau with no slope change.
- **Cache infrastructure failure.** The cache is an in-process dict. There is
  no external cache to fail and no `cache_error` log line.
- **Card-testing attack inflating cache keys.** Would raise authorization
  volume too, and would not step exactly at a config reload that sets TTL to 0.
- **`4b56e1d`**, the revision actually named in the deploy record. One
  docstring line.
- **`087e524`** as *root* cause. A larger pool creates no load. It removed a
  bound and deepened the collapse — contributing, not causal.

---

## The change

**Root cause** — `services/risk_gateway/config.py`

- `CACHE_TTL_SECONDS` `0` → `300`.

**Contributing factors closed here** — same file, each a `CLAUDE.md`
reliability rule that was already being violated before the incident:

- `REQUEST_TIMEOUT_SECONDS` `None` → `1.0`. An attempt with no deadline of its
  own inherits the 8.5s edge budget, which is why p99 pinned at the budget
  rather than at anything the dependency was doing. `(2 + 1) × (1.0 + backoff)`
  stays inside 8.5s.
- `RETRY_ATTEMPTS` `3` → `2`, `RETRY_BACKOFF_BASE_SECONDS` `0.0` → `0.05`,
  `RETRY_JITTER` `False` → `True`.
- `MAX_CONNECTIONS` `512` → `256`, reverting `087e524`.

**Client changes that make those constants real** — `services/risk_gateway/client.py`

- Backoff is now applied with **full jitter**, and not after the final attempt.
  `RETRY_JITTER` was previously read only by `simulation.py` and the ops
  console — the client ignored it entirely, so the flag was decorative.
- `_ResponseCache` prunes expired entries on read and is bounded by
  `CACHE_MAX_ENTRIES`. It previously had **no eviction path of any kind**:
  `get` treated expired entries as misses but never removed them and `put`
  wrote unconditionally, so the dict only ever grew. See "the change did not
  achieve its stated goal" below.

**Deliberately not changed.** `CIRCUIT_BREAKER_ENABLED` stays `False`. The flag
is read by `simulation.py` and `services/console/health.py` but **not by
`client.py`** — there is no breaker in the request path. Turning it on would
move the capacity model and the ops-console health tile to green while changing
nothing in production. It is now commented as unimplemented, and a test asserts
it stays off until someone builds it.

---

## Root cause

`CACHE_TTL_SECONDS` was set to `0` in `b745a5a`. In `_ResponseCache.get`, the
freshness check is `(time.monotonic() - entry[0]) > self.ttl`, which is true for
every read once the TTL is zero, so every lookup became a miss.

The commit message reads: *"This frees the largest allocation. Latency headroom
on the dependency is fine, so this should be neutral for the auth path."* That
reasoning was sound given what was written down. `ops/slo.yaml` recorded
`capacity_rps: 155` with no indication that 155 was demand measured *after* the
cache, and nothing in the repository connected the TTL constant to the capacity
number. The cache was documented as an optimisation — *"caching absorbs most of
the load"* — and read in review as one.

**Five whys:**

1. Authorizations were declined → the risk gateway could not get a decision and
   fails closed, correctly.
2. Why no decision → every call exhausted its retries against a saturated
   dependency.
3. Why saturated → offered load was ~7x capacity.
4. Why 7x → the cache stopped absorbing ~77% of calls (2.7x), and retries
   without backoff multiplied what was left (a further 2.7x).
5. Why did that ship → **the cache was load-bearing capacity that was
   documented as an optimisation, and no test or SLO artifact tied the TTL
   constant to the dependency's capacity number. A capacity change was reviewed
   as a memory tuning knob.**

That last line is the finding. The trigger was a one-line config change; the
system had no way to tell anyone it was a capacity change.

---

## Contributing factors

1. **The cache was capacity and nothing said so.** Even with a perfectly
   hardened call policy — timeout, backoff, jitter, a working breaker — a 0%
   hit rate is still ~2.7x capacity. No retry policy survives losing the cache;
   this was never a "we should have had better retries" incident.
2. **No timeout on a tier-1 synchronous call.** Violates reliability rule 1 and
   converts "slow" into "the whole 8.5s edge budget, four times over".
3. **Retries with no backoff and no jitter.** Violates reliability rule 2. This
   is the amplifier that took 2.7x to 7.2x and made the bad state *stable*.
4. **The circuit breaker does not exist**, but three places in the codebase
   behave as though it might. A responder reaching for it during an incident
   would have turned the health tile green and changed nothing.
5. **CI could not see this class of change.** The full suite passed on the
   incident-causing config. Both cache tests in `test_client.py` construct
   `FraudClient` with an explicit `cache_ttl_seconds=120`, bypassing the module
   constant; `test_capacity.py` asserts against a hand-written `HEALTHY` config,
   never the live one. Nothing asserted the shipped config was survivable.
6. **Raising `MAX_CONNECTIONS` removed the last backpressure.** The gateway
   fast-fails when the pool is full, which is crude load shedding; doubling it
   let twice the concurrency pile onto a 155 rps dependency before shedding
   began (`connection_pool_saturated in_use 512, queued 3118`).
7. **Failed authorizations are not idempotent**, so merchant retries re-enter
   the amplifier at full cost. See follow-up 1 — not fixed here.
8. **Deploy records name a revision, not a payload.** Anyone correlating
   `deploys.txt` against `git show <revision>` saw a docstring.
9. **The change did not achieve its stated goal.** `_ResponseCache` had no
   eviction and no size bound, so with `TTL=0` the dict still grew without
   limit. The memory-pressure alert in TESS-2287 would not have been fixed —
   the actual memory bug is unbounded growth, which a zero TTL makes worse.

---

## What went well

- **The runbook was right and was specific enough to be actionable.** It names
  metastable failure, says to ask what raised the *offered load* rather than
  what made the dependency slow, warns that flat authorization volume does not
  mean flat load on the model, and points at `config.py` as a known gap. Every
  one of those was load-bearing in this investigation.
- **The capacity model turned an argument into a measurement.** Being able to
  run the live config through `simulation.py` and land within 1.8% of four
  observed steady-state values is what moved this from "the deploy looks
  related" to a proven root cause, in seconds rather than hours.
- **Risk scoring failed closed, correctly.** This was expensive, and it was the
  right trade. Approving 41,300 unscored authorizations would have been a much
  worse day.
- **The evidence bundle was complete.** Metrics spanning the inflection, logs
  from before and during, a representative trace with `queue.wait_ms` broken
  out, and a full deploy timeline. The trace attribute that proved the
  dependency was healthy was there because someone chose to record it.

---

## Action items

### Prevent

| # | Action | Owner | Due |
|---|---|---|---|
| P1 | **Done in this PR.** Restore the TTL; assert the shipped config survives the capacity model in CI. | risk-platform | — |
| P2 | **Done in this PR.** Record in `ops/slo.yaml` that `capacity_rps: 155` is post-cache, and that the TTL is a capacity control. | risk-platform | — |
| P3 | Gate config changes to `services/risk_gateway/config.py` behind a required review from risk-platform, and surface the capacity-model delta in the PR body. | risk-platform | 2026-10-04 |
| P4 | Make deploy records list their payload (`git log <last-deployed>..<revision>`) rather than the tip revision alone. | platform-infra | 2026-10-11 |

### Detect

| # | Action | Owner | Due |
|---|---|---|---|
| D1 | Alert on `cache_hit_rate` dropping below 0.5 over 5m. It moved a full minute before authorization success did — this incident had a minute of free warning nobody could act on. | risk-platform | 2026-10-04 |
| D2 | Page on `fraud_model_rps` exceeding 60% of `capacity_rps`, so overload is caught before the fail-closed path converts it into declines. | risk-platform | 2026-10-04 |
| D3 | Reconcile the impact counters. 420 auth/s at 29.2% failure implies ~123 declines/s; the logs report 80/s and `alert.json` implies ~18/s over the observed window. One of those is wrong and it is the number that goes to merchants. | payments-platform | 2026-10-11 |

### Mitigate

| # | Action | Owner | Due |
|---|---|---|---|
| M1 | Implement the circuit breaker in `client.py`, then enable the flag and delete the guard test. In the model a breaker cuts attempts 2.67 → 1.00 and offered load 1122 → 420 rps. Contains blast radius; does not restore capacity. | risk-platform | 2026-10-18 |
| M2 | Persist a terminal result against the idempotency key when the fraud model is unavailable (follow-up 1). | payments-platform | 2026-10-11 |
| M3 | Size `MAX_CONNECTIONS` against dependency capacity (~7 concurrent at 45ms), or add explicit load shedding. At 256 or 512 it is a resource bound, not a shedder. | risk-platform | 2026-10-18 |

---

## Follow-ups deliberately left out of this PR

**1. Failed authorizations are not idempotent.** In
`services/payments_api/service.py`, `authorize()` calls `fraud_client.score()`
and lets `FraudModelUnavailable` propagate without writing anything to the
idempotency store — while the adjacent `risk_decline` path does persist. A
merchant retrying a failed authorization therefore re-enters at full cost: four
more upstream attempts against a dependency that is already saturated. During
INC-4412 this fed the amplifier from outside.

`CLAUDE.md` money rule 4 requires the result to be persisted against the key
before responding, so this is a standing violation independent of the incident.
It is left out because it changes money-path semantics — what a retried, failed
authorization returns — and deserves its own review with `payments-reviewer`
rather than being bundled into an incident fix.

**2. The circuit breaker** (M1) — a real implementation needs shared state
across pods and half-open probe behaviour. Not a change to make under incident
pressure.

---

## Testing

`services/risk_gateway/tests/test_inc_4412_regression.py` — 13 tests. The
headline assertion runs the capacity model against `config_from_module()`, so it
reads the config the service actually ships with. This is precisely what no
existing test did.

**Verified in both directions.** With `config.py` reverted to its INC-4412 state
(client fix retained, to isolate the root cause):

```
9 failed, 4 passed
```

```
E  AssertionError: offered= 1122.6 rps  capacity= 155.6 rps  utilization= 7.22
   cache_hit=  0%  attempts=2.67  p99=  8.50s  success=70.8%
E  assert not True
```

With the fix applied: **13 passed**. Full suite: **115 passed, 1 xfailed**
(baseline on `main` was 101 passed, 1 xfailed).

The suite covers three things: that the live config leaves headroom and meets
the SLO; that each reliability rule the incident violated is now held, including
that jitter actually reaches the request path; and a characterisation of the
incident configuration itself, pinned to the observed 0.708 success rate, so the
mechanism stays legible to the next reader.

`test_the_module_default_ttl_actually_caches` is the cheapest of them and would
have caught this on its own — it constructs `FraudClient` without overriding
`cache_ttl_seconds` and asserts that ten identical scores produce one upstream
call.

### A note on the console test changes

Six tests in `services/console/tests/` failed against the fix because they
sourced their "seeded degraded config" by reading the live working-tree
`config.py` — so they only passed while INC-4412 was unfixed.

This is the exact conflation `health.py`'s own module docstring warns about:
*"a headless triage run edits `services/risk_gateway/config.py` on a branch in
the same working tree, so a tile that read the working tree would turn green
while the fix was still an unreviewed diff."* The tests had the bug the module
was designed to avoid.

The seeded config is now pinned as a constant in `conftest.py`, so the console
fixtures represent the incident regardless of the repo's current state. No
console behaviour changed; `parse_config` is still exercised against the live
file, for whatever it currently contains.

---

## Confidence

**High on the root cause.** The one-line diff shipped at 14:02:07, the metrics
stepped at 14:03:00, the code-level behaviour is direct (`ttl = 0` makes the
freshness check false for every read), and the capacity model started from the
live config lands on all four observed steady-state values within 1.8% — with
the pre-deploy config landing on all four pre-incident values.

**Gaps a reviewer should know about:**

- **No recovery data.** The bundle ends at 14:40 with success still at 0.7066.
  The README says "mitigated" but nothing records how or when, and `main` still
  carried `CACHE_TTL_SECONDS = 0`, so whatever was done in production never
  landed in git. **Worth confirming what is actually running before merging** —
  if the TTL was restored by hand on the pods, this PR is codifying it; if it
  was not, this PR is the mitigation and should be treated with that urgency.
- **Impact counters do not reconcile** (D3). The blast-radius numbers quoted in
  this postmortem come from `alert.json` and may be understated by up to ~6x.
  This affects the impact figure, not the root cause.
- **Rollout mechanics are inferred.** `config_reloaded` logs at 14:02:00 against
  ArgoCD's 14:02:07; log timestamps appear rounded. The intermediate minutes
  fit metric smoothing, but there is no per-pod telemetry to separate smoothing
  from rollout progress. The endpoints are unambiguous either way.
- **Not treated as evidence:**
  `services/console/tests/fixtures/stream_json_sample.jsonl` is a canned demo
  transcript that asserts a root cause and names a SHA (`d04bd8a`) that does not
  exist in this repository. The findings above rest on the diff, the metrics and
  the simulation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
