# Beat 3.2 — captured validation

`/validate-model ml/notebooks/01_fraud_exploration.ipynb`, `model-validator`
agent. Numbers reproduce with `uv run python demo/verify_leakage.py`.

---

## Finding: `card_chargeback_rate` is target leakage. The entire reported lift is an artifact.

Cell 6 of the notebook:

```python
card_cb_rate = df.groupby("card_token").chargeback_filed_at.apply(lambda s: s.notna().mean())
```

Three things are wrong with this, compounding:

**1. The aggregate is computed over the full dataset**, `df`, not over the
training split. Every test-set row's feature value was computed using test-set
outcomes.

**2. It includes each row's own outcome.** A card averaging 10 transactions
contributes its own chargeback to its own rate. For the many cards with two or
three transactions, this approaches handing the model the label.

**3. It is not available at scoring time.** This is the one that matters most.
Chargebacks arrive 20–90 days after the transaction they dispute — median 54
days in this dataset, per `ml/data/generate.py`. At authorization time, a
card's chargeback history contains nothing about the transaction being scored.
The notebook's own closing note half-recognises this: *"how does this get
computed at scoring time? the batch job only refreshes nightly."* The problem
is not staleness. The data does not exist yet.

## Quantified

Rebuilt with a point-in-time cutoff — same feature, counting only chargebacks
**already filed** at the moment of scoring — on the same temporal split:

| Feature set | AUC | PR-AUC |
|---|---|---|
| baseline (observable features only) | 0.7782 | 0.1640 |
| `+ card_chargeback_rate` (full data) | **0.9059** | **0.3578** |
| `+ card_chargeback_rate_pit` (point-in-time) | 0.7775 | 0.1562 |

**Honest lift: −0.0008 AUC.** Within noise of zero — say "within noise of
zero", not "exactly zero"; the number on screen is negative.

The feature is not "somewhat optimistic". Computed correctly it is worth
nothing at all, and the entire +0.128 was the model reading the answer.

The correlation of 0.285 with the label in cell 9 should have been the tell —
nearly double the best observable feature (`amount_log`, 0.160), and the only
one in the set derived from an outcome column. A feature built from
`chargeback_filed_at` that out-correlates everything knowable at authorization
is evidence of leakage, not of signal.

## Verdict: do not ship

Had this reached production it would have scored at roughly baseline while the
backtest promised a 13-point improvement. The failure would have been silent
until someone compared booked performance against the backtest, typically one
to two quarters later.

## Also worth fixing

- **Threshold-free metrics only.** At a 3.5% base rate, report recall at the
  actual review capacity. AUC flatters everything at this imbalance.
- **No time-sliced evaluation.** Aggregate holdout performance hides
  degradation within the window.
- **The temporal split is right** — worth saying, since it is the thing most
  people get wrong. `df.timestamp.quantile(0.70)` with no shuffle is correct.
- **No model card**, and `model-validation.yml` requires one.

## What should happen next

Drop the feature. The baseline at 0.778 is the honest starting point. The
unfinished velocity features in cell 11 are the promising direction: card
transaction counts in a trailing window are genuinely available at scoring
time, and the cell is abandoned rather than wrong.
