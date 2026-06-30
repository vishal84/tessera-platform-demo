---
name: ledger-invariants
description: Double-entry rules for any change touching services/ledger/, payment posting, refunds, captures, or money movement. Use when writing or reviewing ledger entries, adding a payment flow, or changing how amounts are split.
---

# Ledger invariants

The ledger is the source of truth for money at Tessera. Auditors read it
directly. These rules are not style; breaking one is a financial control
failure.

## The five rules

**1. Every transaction balances.** Total debits equal total credits, in the
same currency, in the same transaction. There is no such thing as a one-sided
entry. `Transaction.__post_init__` enforces this — do not route around it.

**2. Money is integer minor units.** `int`, always. Not `float`, not
`Decimal`, not a string. A float cent error is invisible in testing and shows
up as an unexplained break at quarter close, by which point finding it costs
days.

**3. Posted entries are immutable.** Never edit, never delete. A correction is
a new compensating transaction that references the original. The ledger is
append-only because the audit trail is the product.

**4. Cumulative state is derived, never stored twice.** "How much has been
refunded against this payment" is computed from the ledger
(`refunded_total()`), not tracked in a column that can drift. Two sources of
truth means one of them is wrong and you do not know which.

**5. Bounds are checked against derived state.** A refund cannot exceed
`captured_total() - refunded_total()`. Check against the ledger, not against
what the caller claims.

## Writing a new flow

Work out the postings before writing code. For every flow, answer: which
accounts move, in which direction, and do the two sides sum equal?

A capture of 10,000 minor units with a 290 fee:

```
DEBIT   card_network_receivable   10000
CREDIT  merchant_payable           9710
CREDIT  fee_revenue                 290
                        debits 10000 = credits 10000
```

Then write the test that asserts `ledger.is_balanced()` **before** the
implementation. If you cannot state the postings, you do not yet understand
the flow well enough to implement it.

## Partial amounts

Partial flows are where this gets interesting, and where bugs live.

- The remaining refundable amount is `captured_total - refunded_total`. Derive
  it every time; never cache it.
- Fees on a partial refund must be apportioned, and the apportionment must be
  stated explicitly. Refunding 30% of a capture refunds 30% of the fee — unless
  the merchant agreement says fees are non-refundable, in which case the fee
  posting is omitted entirely and the merchant bears it. These are different
  numbers; pick deliberately and write down which.
- Rounding a proportional fee will not divide evenly. Decide where the
  remainder goes and test that N partial refunds summing to the full capture
  leave every account at exactly zero. Off-by-one-cent across a million
  transactions is a real and recurring source of breaks.

## Before you finish

- [ ] `ledger.is_balanced()` asserted in a test
- [ ] Partial amounts summing to the total leave all accounts at zero
- [ ] Bounds derived from the ledger, not from the request
- [ ] No mutation of an existing transaction anywhere in the diff
- [ ] No float touched money at any point
