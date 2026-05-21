# Architecture

## The authorization path

Everything that matters about this system is on one path: a cardholder taps,
and roughly 400 times a second we have to decide yes or no in under a second.

```
   card terminal
        │
        ▼
  ┌─────────────┐   idempotency key
  │ payments-api│───────────────────┐
  └──────┬──────┘                   │
         │ score (blocking)         ▼
         ▼                   ┌─────────────┐
  ┌─────────────┐            │ idempotency │
  │ risk-gateway│            │   store     │
  └──────┬──────┘            └─────────────┘
         │ http
         ▼
  ┌─────────────┐
  │ fraud-model │   capacity ~155 rps
  └─────────────┘
         │
         ▼  (on capture)
  ┌─────────────┐
  │   ledger    │   append-only, double-entry
  └─────────────┘
```

## Things worth knowing before you change something

**The fraud model call is synchronous and blocking.** Every authorization
waits on it. It fails closed: no decision means decline. This makes it the
most dangerous dependency in the system — slowness there is declines here.

**The ledger is append-only.** Corrections are compensating entries. Auditors
read it directly, so the history is the product, not an implementation detail.

**Idempotency is enforced at the edge**, in `payments_api/idempotency.py`. The
current implementation is a `get` followed by a `put` around the money
movement, which is worth looking at closely if you are touching that path.
