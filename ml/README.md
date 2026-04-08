# ml/

Models and features for fraud, credit and customer behaviour.

| Path | State |
|---|---|
| `data/generate.py` | Synthetic transactions. The only source of data in this repo. |
| `features/base.py` | Point-in-time-safe base features. Tested. |
| `features/aggregates.py` | Historical aggregates. **Does not exist yet** — see below. |
| `fraud/` | Production fraud pipeline. **Does not exist yet.** |
| `notebooks/01_fraud_exploration.ipynb` | Where v3 currently lives. Messy. |
| `notebooks/02_credit_scoring_draft.ipynb` | Draft scorecard. Not reviewed. |
| `profiles/segments.py` | Behavioural segmentation. Scaffolding. |

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
