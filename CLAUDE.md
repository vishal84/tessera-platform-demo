# Tessera Financial -- platform monorepo

Card issuing and payments. We are PCI-DSS Level 1 and SOC 2 Type II. Money
moves through this code, so the conventions below are not stylistic
preferences -- several of them are audit findings waiting to happen.

## Domain glossary

| Term | Meaning |
|---|---|
| **authorization** | Reserving funds on a card. No money moves. Expires in 7 days. |
| **capture** | Settling a prior authorization. Money moves. Can be partial. |
| **refund** | Returning captured funds. Can be partial, never exceeds captured. |
| **void** | Cancelling an *uncaptured* authorization. Not the same as a refund. |
| **minor units** | Integer cents. We never use floats for money. Ever. |
| **idempotency key** | Client-supplied key making a mutating request safe to retry. |
| **PAN** | Primary Account Number -- the card number. Never logged, never stored. |
| **CHD** | Cardholder data. PAN, CVV, expiry, track data. In PCI scope. |

## Money rules (non-negotiable)

1. **Money is `int` minor units.** Never `float`, never `Decimal` at API
   boundaries. A float cent error compounds across a million transactions and
   shows up as an unexplained ledger break at quarter close.
2. **Every money movement is double-entry.** Debits equal credits, always. See
   the `ledger-invariants` skill -- it is loaded automatically for ledger work.
3. **Never mutate a posted ledger entry.** Corrections are new compensating
   entries. The ledger is append-only; auditors read it.
4. **Every mutating endpoint takes an idempotency key**, and the result is
   persisted against that key before responding.

## Security rules (non-negotiable)

1. **Never log CHD.** Not in debug, not temporarily, not "just locally". The
   `pii_scan` hook will catch it; do not make it do that work.
2. **Never read or write `.env`, key material, or `infra/prod/`.** Blocked by
   `protect_secrets.py`. Config changes go to `.env.example` + `docs/config.md`.
3. **Tokens, not PANs.** Internal services pass `tok_*`; only the card
   processor adapter sees a PAN, and it holds it for the length of one call.
4. **No new outbound network destinations** without an entry in
   `docs/egress.md`. Exfiltration looks exactly like a feature at review time.

## Reliability rules

1. **Every outbound call has a timeout.** No exceptions. An unbounded call is
   how one slow dependency takes down the authorization path.
2. **Retries need backoff and jitter.** Naive retries turn a slow dependency
   into an outage -- they amplify load precisely when the system has least
   headroom. See `ops/runbooks/risk-gateway.md`.
3. **Fail the right way.** Risk scoring fails *closed* (decline). Non-critical
   enrichment fails *open*. If you are unsure which a call is, ask.

## Layout

```
services/payments_api/   FastAPI edge: authorize, capture, refund, void
services/ledger/         Double-entry core. The source of truth for money.
services/risk_gateway/   Calls the fraud model. On the synchronous auth path.
services/console/        Ops console API: incident triage runs, PRs, guardrail audit
web/                     Ops console UI (Vite + React). Built output is served by services/console
ml/                      Fraud, credit, behavior models + feature definitions
ml/registry/             Model registry and shadow-run reports
ops/                     SLOs, runbooks, incident evidence bundles
```

## Conventions

- Python 3.11+, `uv` for dependency management, `pytest` for tests.
- Type hints on every public function. `str | None`, not `Optional[str]`.
- Tests live next to the code in `tests/` inside each service package.
- Structured logging only: `logger.info("event_name", extra={...})`.
- Commits: conventional commits (`feat:`, `fix:`, `perf:`, `chore:`).

## Running things

```bash
uv sync                          # install
uv run pytest                    # all tests
uv run pytest services/ledger    # one package
uv run python -m ml.data.generate  # regenerate synthetic data
```

There is no real cardholder data anywhere in this repo, and there never will
be. `ml/data/generate.py` produces synthetic transactions. If you need a card
number for a test, use the published test PANs in `tests/fixtures/`.
