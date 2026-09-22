# Model card: fraud-v3-candidate

| | |
|---|---|
| Model | `fraud-v3-candidate` (registry: `ml/registry/models.json`) |
| Champion it is measured against | `fraud-v2`, production since 2026-02-12 |
| Owner | ml-fraud |
| Ticket | TESS-2310 |
| Status | **Blocked. Recommendation: do not promote.** |
| Defined by | `ml/fraud/pipeline.py` (features, split, model, operating point) |
| Validation | `ml/validation/` -- Gate 1 pass, Gate 2 pass, Gate 3 pass with a warning, Gate 4 report written (details below) |
| Investigation | `ml/notebooks/03_v3_shadow_investigation.ipynb`, executed |

## The headline, first

The 0.906 AUC recorded for this model in the registry is not a number this model
can produce. It was measured with a `card_chargeback_rate` computed over the whole
training table, which for every training row included that row's own chargeback,
filed 20-90 days after the transaction. At scoring time that dispute does not
exist. Scored honestly, the candidate is the champion: 0.779 AUC against 0.780,
PR-AUC 0.159 against 0.160, on the same temporal holdout. In shadow, the model
trained on the leaked feature scored 0.699, *below* the champion, because it had
learned to depend on a feature that does not exist at serving time; the
investigation notebook reproduces all four shadow numbers to four decimals from
that one mechanism.

This card documents the model as `ml/fraud/pipeline.py` now defines it: the
champion's observable features plus a **point-in-time** card chargeback rate.
It is the honest candidate. It does not beat production.

## Purpose and scope

**Decision.** Rank card authorizations by fraud likelihood so that the top
`REVIEW_BUDGET` = 5% of scores go to manual review. The score is an ordering
for a review queue, not an approve/decline decision on its own; the
authorization path's fail-closed behaviour on risk-gateway errors is unchanged
by this model.

**Population.** Card-present and card-not-present authorizations on Tessera-
issued cards, scored synchronously at authorization time.

**Not for.** Credit decisions of any kind. Merchant risk decisions. Any use
where the output is an adverse action against a cardholder without human
review. No feature here has been validated against a protected characteristic,
so the model must not be used to set per-customer limits or pricing.

## Training data

| | |
|---|---|
| Source | `ml/data/generate.py`, synthetic. There is no real cardholder data in this repository. |
| Rows | 60,000 transactions, 6,000 cards, 400 merchants, 4,500 devices |
| Window | 2026-03-01 to 2026-08-27 (180 days) |
| Base rate | 3.51% fraud; ~85% of fraud is eventually disputed, 20-90 days later (median 54) |
| Split | **Temporal.** Rows at or before the 70th percentile of time train; the rest hold out. Cutoff 2026-07-05 01:06 UTC. Train 42,000, holdout 18,000. The holdout is the shadow window. |
| Labels | `is_fraud`, fully known for the synthetic table. In production, labels mature over 90 days; the holdout metrics below assume mature labels. |

A random split on this data would be a finding on its own; the pipeline
cannot produce one.

## Features

The column reviewers should read first is **when known**. Every feature is
computed by `ml/features/base.py` or `ml/features/aggregates.py`; there is no
other path into the model.

| Feature | Definition | When known | Kind | Notes |
|---|---|---|---|---|
| `amount_log` | log1p(amount in minor units) | At authorization | Row | |
| `hour_of_day` | UTC hour of the transaction | At authorization | Row | |
| `is_night` | 1 if 01:00-05:00 UTC | At authorization | Row | Proxy risk: time zone correlates with geography. See fairness. |
| `is_cross_border` | 1 if issuing and acquiring country differ | At authorization | Row | **Proxy for country / national origin.** See fairness. |
| `mcc_risk_tier` | Merchant category mapped to a 1-5 tier from a published network-level statistic | At authorization | Row | Not derived from our labels. |
| `amount_zscore_within_mcc` | z-score of log amount within the transaction's MCC | At authorization for the row; the mean and std are frame-wide | Row, frame-wide statistic | Gate 1 reports this as an advisory: the mean and std are fit over the whole table rather than frozen at training time. Not target leakage. Should be frozen and versioned before this ships (limitation 3). |
| `card_chargeback_rate` | Chargebacks on this card **filed before** `as_of`, divided by transactions on this card **before** `as_of`. 0.0 when the card has no history. | Aggregate, point-in-time. `as_of` = **the transaction's own timestamp** (`aggregates.scoring_time_as_of`). | Historical aggregate, served from the `card_history` batch | See below. |

**`card_chargeback_rate`, in full**, because it is the feature this card exists for:

- *`as_of` cutoff used in training:* each transaction's own timestamp, strict
  inequality, so a row never sees itself. This is the cutoff under which the
  shadow run's feature statistics reproduce exactly (non-zero share 0.1419);
  a midnight cutoff gives 0.1411 and 0.6997 AUC instead of 0.6992. If platform
  confirms the batch is served a day stale, `pipeline.serving_cutoff` is the
  one place to change, and the holdout difference is 0.0005 AUC.
- *Staleness at serving:* the shadow evidence says the feature is fresh to the
  transaction. If it is a nightly batch, up to 24 hours stale. This must be
  confirmed with platform (open item 2).
- *What it was before this PR:* one rate per card over the whole table
  (`ml/notebooks/01_fraud_exploration.ipynb`, cell 8). That definition is kept
  as `ml/validation/tests/leaky_fixtures.py` and Gate 1 is tested to fail on
  it.
- *Signal:* on this data, none. Single-feature AUC on the holdout is 0.498. The
  generator assigns cards to transactions uniformly at random, so a card's
  past does not predict its future. Real portfolios may differ; that is a
  hypothesis to be tested with this definition, not a result anyone has seen.

The model has no access to `is_fraud` or `chargeback_filed_at` except through
`card_chargeback_rate`'s cutoff logic; `pipeline.observable_frame` strips the
label before any feature function runs, and a feature that reaches for it
raises.

## Performance

Gate 2, `python -m ml.validation.performance --min-pr-auc 0.15`, on the
temporal holdout, operating point = top 5% of training scores (threshold
0.1300):

| slice | n | fraud | AUC | PR-AUC | flag rate | recall | precision |
|---|---|---|---|---|---|---|---|
| holdout | 18,000 | 635 | 0.7788 | 0.1590 | 0.0525 | 0.2835 | 0.1905 |
| 2026-07 | 9,074 | 327 | 0.7683 | 0.1541 | 0.0515 | 0.2661 | 0.1863 |
| 2026-08 | 8,926 | 308 | 0.7900 | 0.1663 | 0.0536 | 0.3019 | 0.1946 |
| champion (same split) | 18,000 | 635 | 0.7802 | 0.1602 | 0.0509 | 0.2850 | 0.1974 |

Gate 2 passes the floor. Its own advisory is the important line: **the
candidate does not beat the champion** on either metric. The gap (0.001 AUC,
0.001 PR-AUC) flips sign depending on how tied timestamps are ordered when the
table is loaded, which is to say there is no gap.

For context, the numbers that preceded this card:

| | AUC | PR-AUC | what it measured |
|---|---|---|---|
| notebook 01, offline | 0.906 | 0.358 | the leak |
| shadow, 2026-07-05 to 2026-08-27 | 0.699 | 0.071 | the leak-trained model served the honest feature |
| this card | 0.779 | 0.159 | the honest candidate |

The champion baseline in the table is the `base.py` feature set trained on the
same split, not a byte-for-byte reproduction of `fraud-v2` as deployed (which
also carries `device_card_count`). The two score the same on this holdout
(0.780 vs the registry's 0.778); reproducing `fraud-v2`'s exact serving is
open item 4.

## Fairness

Gate 4, `python -m ml.validation.fairness --report fairness.md`. No protected
attribute exists in the data and none is an input. Every dimension below is a
proxy. Ratios are against the largest slice in the dimension; `review` marks
an FPR ratio outside 0.8-1.25.

**Country / cross-border** (identical slices: in the generator `country` is
`GB` exactly when `is_cross_border` is 1):

| slice | n | fraud rate | AUC | flag rate | recall | FPR | precision | FPR ratio |
|---|---|---|---|---|---|---|---|---|
| cross-border (GB) | 1,428 | 0.1015 | 0.7401 | 0.2633 | 0.5793 | **0.2276** | 0.2234 | **7.74** |
| domestic (US) | 16,572 | 0.0296 | 0.7629 | 0.0343 | 0.1959 | 0.0294 | 0.1687 | 1.00 |

A legitimate cross-border transaction is **7.7 times** more likely to be held
for review than a legitimate domestic one. Cross-border traffic does carry
3.4 times the fraud rate, and `is_cross_border` is a direct input, so this is
the model doing what it was built to do -- but it is also the model treating
country as a risk factor, and in a real portfolio country is a proxy for
national origin. This disparity is reported, not resolved. Options for the
reviewer: a per-segment operating threshold that equalises FPR, removing
`is_cross_border` and measuring the cost, or accepting the disparity with a
documented business justification. None of those is a decision this card
makes.

**Time of day**: the 00-05 band has FPR 0.119 against 0.019 for 06-11 (ratio
6.4). `is_night` is an input and the fraud rate in that band is 6.7% against
2.3%. Same shape as cross-border: a legitimate night-time transaction is held
six times as often. Time zone correlates with geography.

**Merchant category**: FPR ratios from 0.39 (grocery, 5411) to 2.53 (betting,
7995). `mcc_risk_tier` is an input.

**Amount band**: FPR rises from 0.35% below 1,000 minor units to 26% at
20,000-99,999 and 72% at 100,000 and above (n=53, small slice). Amount is the
model's strongest observable feature and large transactions are where the
money is; this is expected, and it is also where a false positive costs the
cardholder most.

Full tables: `fairness.md`, produced by the gate.

## Limitations and failure modes

1. **No honest lift.** The feature this candidate adds carries no signal on
   this data. There is no reason in these numbers to promote it.
2. **`card_chargeback_rate` is non-stationary in this table.** Gate 3 reports
   PSI 0.2499 between the training and recent windows, at the 0.25 limit.
   Cause: the table starts on 2026-03-01 with no card history, so the
   feature's non-zero share climbs from 0% in March to 16% in August as
   history accumulates. Trimming the cold start from the training side brings
   the PSI down monotonically (0.21 from April, 0.16 from May, 0.10 from
   June). This is left-censoring of the synthetic data. On production data
   with mature histories the feature should be stationary, and that has to be
   measured before it is trusted: the gate will fail if it is not.
3. **`amount_zscore_within_mcc` is fit over the whole frame.** Its per-MCC
   mean and std should be frozen at training time and versioned with the
   model. Until then, the serving value drifts as the population does, and a
   new MCC gets a NaN-derived 0.0.
4. **Missing or stale `card_chargeback_rate`.** The feature is 0.0 for a card
   with no history, and "no history" and "never disputed" are indistinguishable
   by design. If the `card_history` batch fails, every card silently looks
   clean; the model then behaves as the champion plus noise. Monitoring must
   alarm on the feature's non-zero share, not on the model's accuracy.
5. **Cross-border and night-time false positive rates** are six to eight
   times the reference. See fairness.
6. **Under-represented populations.** The largest amount band has 53 holdout
   rows. Cross-border is 8% of traffic. Per-slice AUCs in those cells are
   estimates with wide intervals.
7. **The shadow report's registry numbers are wrong** and remain in
   `ml/registry/models.json` (`auc_holdout: 0.906`). Correcting the registry
   is the model platform's action, not this PR's.

## Monitoring plan

Label feedback arrives 20-90 days late, so accuracy is the last alarm, not the
first. Owner for all of the below: ml-fraud, paging via the risk-gateway
on-call rotation.

| Signal | Threshold | Cadence | Why |
|---|---|---|---|
| `card_chargeback_rate` non-zero share, per day | Alert if it falls below half the trailing 30-day median, or is exactly 0 | Daily | A failed `card_history` batch makes every card look clean (limitation 4). |
| Feature PSI vs the training window, each feature | Warn at 0.10, page at 0.25 -- the same thresholds as Gate 3 | Weekly | `card_chargeback_rate` first; it is the only feature that drifted offline. |
| Score distribution PSI vs training | Warn at 0.10, page at 0.25 | Daily | Earliest signal that serving differs from training; it moved a whole month before labels could. |
| Flag rate, overall and by cross-border / night band | Alert if overall leaves 4-6%, or any slice's FPR ratio to reference moves more than 25% from this card | Daily | The operating point is a fixed threshold; a shifting score distribution shows up here first. |
| Recall and precision at the operating point, on matured labels | Alert if recall falls below 0.25 or precision below 0.15 on a 30-day window | Monthly, at 90 days' label maturity | The performance floor, measured late. |
| Shadow-vs-offline reconciliation | Feature non-zero share and mean in shadow must match the training-table values under the same `as_of` | Every shadow run, before reading the metrics | This is the check that would have caught TESS-2310 in an afternoon. |

## Decisions and explanations

This is a fraud-review ranking model, not a credit model; ECOA/Reg B adverse-
action reason codes do not apply to the review-queue decision. Two things
still hold:

- A transaction held for review or declined on the model's score must carry a
  reason the ops console can show. The pipeline does not yet produce a
  per-decision explanation (open item 5). Until it does, the reason recorded
  is "risk score above review threshold", which is true and uninformative.
- If the score is ever used in a decision with cardholder-facing consequences
  beyond a review hold, the country and time-of-day disparities above become
  the first question MRM will ask, and the answer has to already exist.

## Open items

1. Run Gate 3 against a training extract with mature card history; confirm
   `card_chargeback_rate` is stationary. Blocking for any promotion.
2. Confirm with platform how `card_history` is served (fresh to the
   transaction, as the shadow evidence says, or a nightly batch) and set
   `pipeline.serving_cutoff` to match.
3. Freeze `amount_zscore_within_mcc`'s per-MCC statistics at training time.
4. Reproduce `fraud-v2`'s deployed feature set, including how
   `device_card_count` is served, so the champion baseline is the champion.
5. Per-decision explanation for held transactions.
6. Correct the registry entry: `auc_holdout` 0.906 is not reproducible under
   any point-in-time definition. Model platform's call.

## Validation record

Run on 2026-09-22 against the synthetic table at the commit that introduced
this card. Reproducible with the four commands in `ml/README.md`.

| Gate | Command | Result |
|---|---|---|
| 1 point-in-time | `python -m ml.validation.leakage --fail-on-leak` | PASS. No leak; `amount_zscore_within_mcc` advisory. On the notebook-01 definition: LEAK on both blocking probes (tested). |
| 2 performance | `python -m ml.validation.performance --min-pr-auc 0.15` | PASS at PR-AUC 0.1590. Advisory: does not beat the champion. |
| 3 drift | `python -m ml.validation.drift --max-psi 0.25` | PASS with warning: `card_chargeback_rate` PSI 0.2499. |
| 4 fairness | `python -m ml.validation.fairness --report fairness.md` | Report written; 13 slices marked for review, cross-border and night-time being the ones that matter. |
