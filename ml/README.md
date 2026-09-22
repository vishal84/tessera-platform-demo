# ml/

Models and features for fraud, credit and customer behaviour.

| Path | State |
|---|---|
| `data/generate.py` | Synthetic transactions. The only source of data in this repo. |
| `features/base.py` | Point-in-time-safe base features. Tested. |
| `features/aggregates.py` | Point-in-time historical aggregates (`card_chargeback_rate`). Every function takes an `as_of`. Tested. |
| `fraud/pipeline.py` | Production fraud pipeline: features → temporal split → model. The gates validate what this file says ships. |
| `fraud/MODEL_CARD.md` | Model card for fraud-v3-candidate, for MRM. |
| `validation/` | The four merge gates from `.github/workflows/model-validation.yml`. Tested, including a negative fixture. |
| `notebooks/01_fraud_exploration.ipynb` | Where v3 came from. Its `card_chargeback_rate` is the leak; kept as the record. |
| `notebooks/02_credit_scoring_draft.ipynb` | Draft scorecard. Not reviewed. |
| `notebooks/03_v3_shadow_investigation.ipynb` | Why v3 scored 0.906 offline and 0.699 in shadow, with the numbers. Executed in place. |
| `profiles/segments.py` | Behavioural segmentation. Scaffolding. |

## Validation gates

Every change to `ml/` passes these before merge, in this order. Gate 1 runs
first because if a feature leaks, every number the other three produce is
fiction.

```bash
uv run python -m ml.validation.leakage     --fail-on-leak       # Gate 1: point-in-time correctness
uv run python -m ml.validation.performance --min-pr-auc 0.15    # Gate 2: floor on a temporal split
uv run python -m ml.validation.drift       --max-psi 0.25       # Gate 3: training vs recent traffic
uv run python -m ml.validation.fairness    --report fairness.md # Gate 4: per-slice report for MRM
```

`ml/validation/tests/leaky_fixtures.py` keeps the notebook-01 definition of
`card_chargeback_rate` on purpose, and `test_leakage.py` asserts Gate 1 fails
on it. Do not fix the fixture.

## The rule

**A feature may only use information available at the moment of scoring.**

Chargebacks arrive 20–90 days after the transaction they dispute (median 54
days in our data). Any aggregate built from `chargeback_filed_at` without a
time cutoff is telling the model the answer. It will look excellent in
backtest and do nothing in production.

`features/base.py` is safe by construction — every function is a pure function
of one row's observable fields. Historical aggregates are the dangerous kind
and need an explicit `as_of` cutoff.

## There is no real data here

`data/generate.py` produces everything. No cardholder data, no applicant data,
no production extracts. That is not a demo convenience; it is the rule.
