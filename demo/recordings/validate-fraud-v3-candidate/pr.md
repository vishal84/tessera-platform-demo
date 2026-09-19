---
title: "feat(ml): explain the fraud-v3 shadow gap, ship point-in-time card_chargeback_rate and the four validation gates"
branch: ml/TESS-2310-v3-shadow-leakage
base: main
---

## Summary

fraud-v3-candidate scored 0.906 AUC offline and 0.699 in shadow because its one
new feature, `card_chargeback_rate`, was computed over the whole training table
and therefore included, for every training row, that row's own chargeback, filed
20-90 days after the transaction. At scoring time that dispute does not exist.
The offline number measured the leak; the shadow number measured a model that
had learned to depend on it. Scored honestly, the candidate is the champion
(0.779 vs 0.780 AUC). **Do not promote.**

This PR carries the investigation (notebook 03, executed in place), the
point-in-time implementation of the feature, the production pipeline, the four
validation gates the workflow already specified, a negative fixture that proves
Gate 1 fails on the exact definition that reached shadow, and the model card.

Nothing is promoted, deployed or pushed. The registry is untouched; correcting
its `auc_holdout: 0.906` is the model platform's call (see follow-ups).

---

## What the evidence shows

Everything below is in `ml/notebooks/03_v3_shadow_investigation.ipynb` with
outputs.

**The offline number reproduces exactly from notebook 01's code.** Same data,
same 70/30 temporal split, same code: baseline 0.7782 / 0.1640 (the champion's
registered numbers), with the notebook's `card_chargeback_rate` 0.9059 / 0.3578.

**The feature is two different features under one name.** Notebook 01 computes
one rate per card over the whole table. The serving path counts only chargebacks
filed as of scoring time. Both feature statistics in the shadow report reproduce
to four decimals:

| | non-zero share | source |
|---|---|---|
| training rows, notebook definition | **0.2743** | reported 0.2743 |
| shadow window, point-in-time (`aggregates.card_chargeback_rate`, `as_of` = scoring timestamp) | **0.1419** | reported 0.1419 |
| training rows, point-in-time | 0.0344 | what the model should have been trained on |

Of the training rows the notebook definition marks non-zero, **75.7%** had no
filed dispute at all at the transaction's timestamp.

**The lift is the row's own chargeback, and nothing else.** Single-feature AUC on
the shadow window:

| definition | AUC |
|---|---|
| notebook 01 (whole table, own row included) | 0.848 |
| whole table, own row excluded | 0.512 |
| point-in-time | 0.498 |

**The shadow number reproduces from one fitted object.** Take the notebook-01
model as trained and hand it the point-in-time feature:

| | shadow report | reproduced |
|---|---|---|
| AUC | 0.6992 | 0.6992 |
| PR-AUC | 0.0706 | 0.0706 |
| AUC 2026-07 | 0.706 | 0.7060 |
| AUC 2026-08 | 0.695 | 0.6946 |

A midnight (day-stale batch) cutoff gives 0.1411 / 0.6997 instead, so serving is
fresh to the transaction. That is the cutoff the pipeline trains with.

**Why worse than the champion, not merely no better.** In shadow, the 14% of
rows with a non-zero feature have the same 3.5% fraud rate as everyone else, but
the model scores them sixteen times higher; 98% of its review queue is those
rows at precision 0.09 (baseline 0.19). Within the 86% of traffic where the
feature is zero it ranks fraud worse than the baseline (AUC 0.750 vs 0.781),
because it leaned on the feature instead of the observable ones. Net: it fills
half its review budget and recall drops from 0.28 to 0.07.

**Honest retrain: no lift.** Point-in-time in training and holdout, notebook
feature set: 0.7775 / 0.1562 against baseline 0.7782 / 0.1640. Pipeline feature
set (`base.py` + point-in-time aggregate), as CI's Gate 2 prints it: 0.7788 /
0.1590 against champion 0.7802 / 0.1602. The sign of the gap flips with how tied
timestamps are ordered at load; there is no gap. The generator assigns cards to
transactions uniformly, so a card's past does not predict its future in this
data. On a real portfolio that is a hypothesis to test with the honest
definition.

---

## Ruled out

- **Drift between training and shadow windows.** PSI on every base feature is
  below 0.002 and the champion scores 0.778 in both windows. The population did
  not move.
- **Label immaturity in shadow** (labels as of 2026-09-15, window ends
  2026-08-27). The champion is unaffected, both shadow months are equally bad
  (0.706, 0.695), and the fully-labelled reproduction lands on 0.6992 with no
  censoring applied.
- **Nightly-batch staleness.** Midnight vs scoring-timestamp cutoffs differ by
  0.0005 AUC, and the serving stats match the scoring-timestamp cutoff exactly.
- **A serving bug.** The serving feature's non-zero share (0.1419) matches the
  honest definition to four decimals. Serving did the right thing.
- **A different model or hyperparameters in shadow.** One fitted object
  reproduces all four shadow numbers.
- **`device_card_count`.** Also a full-table aggregate in notebook 01, but over
  observable columns only: point-in-time it costs 0.004 AUC. Real, small, not
  the story; Gate 1 reports this class as an advisory. Follow-up 4.

---

## The change

**`ml/features/aggregates.py`** (new). `card_chargeback_rate(df, as_of)`: per
row, chargebacks on the card *filed* before `as_of` over transactions on the
card *before* `as_of`, strict inequality, so a row never sees itself. `as_of` is
a scalar or a per-row Series; `scoring_time_as_of(df)` and
`nightly_batch_as_of(df)` are the two serving cutoffs. `card_history(df, as_of)`
exposes the counts. Vectorised with `merge_asof` on a per-card running count;
0.3s on 60k rows. Rejects a chargeback filed before its own transaction.
15 tests, on a five-row frame you can check by hand.

**`ml/fraud/pipeline.py`** (new). The one place that says what the model is:
`CHAMPION_FEATURES` (= `base.BASE_FEATURES`), `CANDIDATE_FEATURES` (+ the
aggregate), temporal split, `HistGradientBoostingClassifier(max_iter=250,
random_state=0)` as in notebook 01, the 5% review budget. `observable_frame`
strips `is_fraud` before any feature runs; `feature_functions()` binds the
aggregate to `serving_cutoff` so no caller can forget the `as_of`.

**`ml/validation/`** (new), exactly the four commands in
`.github/workflows/model-validation.yml`:

| Gate | Module | What it does | Result on the candidate |
|---|---|---|---|
| 1 | `leakage --fail-on-leak` | Recomputes every feature with disputes filed after a cutoff hidden, then with each row's own dispute hidden; fails if any value moves. Advisory probe for frame-wide statistics; advisory for a single feature with holdout AUC > 0.80. | PASS. On the notebook definition: LEAK on both blocking probes. |
| 2 | `performance --min-pr-auc 0.15` | Temporal split, holdout AUC / PR-AUC / recall and precision at the review budget, by month, champion on the same split. | PASS at 0.1590. Advisory: does not beat the champion. |
| 3 | `drift --max-psi 0.25` | PSI per feature and for the score, training window vs recent (holdout) window. **Mass-point-aware binning**: naive quantile bins collapse to one bin on a 97%-zero feature and report PSI 0 for a feature whose non-zero share quadrupled. | PASS with warning: `card_chargeback_rate` at 0.2499. See "what a reviewer should look at". |
| 4 | `fairness --report fairness.md` | Per-slice metrics at the operating point across country, cross-border, MCC, amount band, hour band; FPR and flag-rate ratios vs the largest slice; four-fifths rule marks `review`. Report-only per the workflow; `--fail-on-disparity RATIO` makes it blocking. | Report written; cross-border FPR ratio 7.7, night-time 6.4. |

**`ml/validation/tests/leaky_fixtures.py`** keeps notebook 01's definition as a
negative fixture. `test_leakage.py` asserts Gate 1 fails on it on every blocking
probe, blames only that feature, and passes on the pipeline's definition;
`test_performance.py` pushes the same fixture through Gate 2 to show it clears
any floor, which is why Gate 1 runs first. Do not fix the fixture.

**`ml/fraud/MODEL_CARD.md`** (new), written with the `model-card` skill. Leads
with the finding, gives every feature's "when known", reports the honest
performance by month against the champion, the fairness disparities with
numbers, and six open items.

**`ml/notebooks/03_v3_shadow_investigation.ipynb`**: 30 cells added to the 5
that were there, executed in place with nbconvert; outputs are in the file.

**Docs**: `ml/README.md` table and a "Validation gates" section; the STATUS
comment in the workflow is updated because it said `ml/validation/` did not
exist.

Started from the timed-out run's `wip/TESS-2310-partial` branch for
`aggregates.py`, its tests, `pipeline.py`, and the Gate 1 module; each was
re-verified against pandas 3.0.6 and scikit-learn 1.9.1 (all pass). Changed
from that branch: the serving cutoff is the scoring timestamp rather than
midnight, because that is what the shadow evidence says, and `card_history` was
added so the notebook decomposes the feature with the production code rather
than a copy.

---

## What a reviewer should look at closely

1. **Gate 3 passes by 0.0001.** `card_chargeback_rate` PSI is 0.2499 against a
   0.25 limit. The cause is visible and benign here: the synthetic table starts
   cold on 2026-03-01, so the feature's non-zero share climbs from 0% in March
   to 16% in August as history accumulates, and trimming the cold start from
   the training side brings PSI down monotonically (0.21, 0.16, 0.10). That is
   left-censoring, not the population moving. I did not tune the gate to make
   this comfortable, and I would rather a reviewer see the number than not.
   On real data with mature histories it should be stationary; "should" is open
   item 1 in the model card and is blocking for any promotion.
2. **The champion baseline is `base.py`'s feature set, not `fraud-v2` byte for
   byte.** `fraud-v2` as registered carries `device_card_count` and a raw MCC
   code; `base.py` carries `mcc_risk_tier` and `amount_zscore_within_mcc`. They
   score the same on this holdout (0.780 vs 0.778). Reproducing the deployed
   feature set is follow-up 4.
3. **The serving cutoff.** The pipeline trains with `as_of` = the transaction's
   timestamp because the shadow stats reproduce under it and not under midnight.
   If platform says the batch is a day stale, `pipeline.serving_cutoff` is one
   line and the cost is 0.0005 AUC. The wip branch had chosen midnight; I
   changed it on the evidence and would like that confirmed.
4. **Gate 4 marks 13 slices for review.** Most are the model's legitimate risk
   drivers (amount, MCC). The two that matter are cross-border (a legitimate
   cross-border payment is held 7.7 times as often) and night-time (6.4 times).
   The card reports them and names the options; it does not decide.
5. **`amount_zscore_within_mcc` is fit over the whole frame.** Gate 1 flags it
   as an advisory, correctly: not target leakage, but a statistic that should
   be frozen at training time. Not fixed here (follow-up 3) because it is the
   champion's feature too and changing it is a separate decision.

---

## Postmortem draft

**Summary.** A fraud-model candidate was registered with 0.906 AUC and blocked
in shadow at 0.699. The offline number was produced by a feature that read each
transaction's own future chargeback. No production decision was affected; the
candidate never left shadow.

**Impact.** None to customers or money. One shadow window (2026-07-05 to
2026-08-27, 18,000 scored transactions) and the engineering time between
registration (2026-09-16) and this PR. Had the candidate been promoted on the
offline number, it would have caught roughly a quarter of the fraud the champion
catches while filling half its review budget.

**Timeline.**

| when | what |
|---|---|
| (last sprint) | `card_chargeback_rate` built on a branch as a per-card `groupby` over the full table; "a huge jump". |
| notebook 01 | Pulled into the v3 exploration. +0.13 AUC. Correlation with the label 0.285, "strongest single feature we've ever had". A note-to-self asks how the feature is computed at scoring time; the question is never answered. |
| 2026-09-16 08:40 | Shadow report generated: 0.699 vs champion 0.778. Status `blocked`. Same day, candidate registered with `auc_holdout: 0.906`. |
| 2026-09-21 | Timed-out agent run leaves partial `aggregates.py`, `pipeline.py` and Gate 1 on `wip/TESS-2310-partial`. |
| 2026-09-22 | This PR. |

Detection gap: the shadow run caught it, which is what shadow runs are for. The
gap that matters is between "huge jump on a branch" and "why is it computed
this way", which was never closed by anything in the system.

**Root cause.** `card_cb_rate = df.groupby("card_token").chargeback_filed_at
.apply(lambda s: s.notna().mean())` in notebook 01 cell 8, mapped onto every
row. For a training row on day D it included the row's own dispute, filed a
median 54 days after D. At serving time the feature was computed from disputes
filed as of scoring time. Same name, two features; the model learned the first
and was served the second.

**Five whys.** The candidate underperformed in shadow → it depended on a feature
whose serving distribution differed from training → the training feature
included each row's own future outcome → the aggregate had no `as_of` cutoff →
**nothing between a notebook and the registry checked whether a feature could
exist at scoring time. The workflow that would have (`model-validation.yml`) was
specified but unimplemented, so a 0.906 offline number went into the registry
on the strength of a notebook cell.**

**Contributing factors.**

1. `ml/features/aggregates.py` did not exist. `base.py`'s docstring pointed at
   it for "the point-in-time implementations"; there was nowhere to put the
   feature except a notebook.
2. The four gates were agreed and written into CI but not implemented, so CI
   failed on every `ml/` change and its failure carried no information.
3. A +0.13 AUC jump from a single feature was read as good news. The
   model-validator agent's first instruction is that a large unexplained
   improvement is a bug; nothing in the path to the registry invoked it.
4. The shadow report recorded the feature's non-zero share in training and in
   shadow (0.274 vs 0.142) and did not compare them. The reconciliation that
   would have explained the gap in one line was one subtraction away.
5. The registry accepted `auc_holdout` from a notebook with no provenance
   beyond "cell 6".
6. Two loaders order tied timestamps differently, which moves third-decimal
   metrics. Harmless here; a reviewer comparing numbers across notebook and CI
   would have been confused by it.

**What went well.** The shadow run existed, ran on the same window as the
holdout, and blocked the promotion. The shadow report recorded the feature
statistics that made the diagnosis a reproduction rather than an argument. The
synthetic generator models dispute lag explicitly, which is why the leak is
demonstrable rather than suspected. `base.py` was already point-in-time-safe by
construction and needed no change. The workflow's contract was written first, so
the gates had a specification to meet rather than a design to argue.

**Action items.**

*Prevent*

| # | action | owner | due |
|---|---|---|---|
| P1 | **Done in this PR.** `aggregates.py` with a mandatory `as_of`; Gate 1 with the notebook definition as a tested negative fixture. | ml-fraud | -- |
| P2 | **Done in this PR.** All four gates implemented with the workflow's flags; CI on `ml/**` now carries information. | ml-fraud | -- |
| P3 | Registry entries require a Gate 2 report artifact, not a notebook cell reference, for `auc_holdout`. | model-platform | 2026-10-09 |
| P4 | Correct `fraud-v3-candidate`'s registry entry (0.906 is not reproducible under any point-in-time definition) or withdraw the candidate. | model-platform | 2026-10-02 |

*Detect*

| # | action | owner | due |
|---|---|---|---|
| D1 | Shadow reports compare training-table and shadow feature statistics under the same `as_of` and fail the report on a mismatch, before any metric is read. | model-platform | 2026-10-16 |
| D2 | Alert on `card_chargeback_rate` non-zero share hitting 0 or halving day over day (a failed `card_history` batch makes every card look clean). | ml-fraud | 2026-10-16 |

*Mitigate*

| # | action | owner | due |
|---|---|---|---|
| M1 | Run Gate 3 against a training extract with mature card history; the 0.2499 PSI must be shown to be left-censoring before any promotion. | ml-fraud | 2026-10-09 |
| M2 | Confirm `card_history` serving semantics with platform (fresh vs nightly) and set `pipeline.serving_cutoff` accordingly. | ml-fraud + platform | 2026-10-02 |

---

## Follow-ups deliberately left out

1. **`fraud-v2`'s exact feature set.** The registry's champion carries
   `device_card_count`, which notebook 01 also computes over the full table and
   which costs 0.004 AUC point-in-time. Whether production serves it
   point-in-time is a question for platform; reproducing it belongs with the
   answer.
2. **Freezing `amount_zscore_within_mcc`'s statistics.** Champion feature;
   separate decision.
3. **Per-decision explanations for held transactions.** Model card open item 5.
4. **`ml/profiles/segments.py`** has the same class of problem (its own
   docstring says so) and is scheduled for next quarter; not touched.

---

## Testing

```
uv run pytest ml/
65 passed in 21.91s

uv run pytest            # whole repository
186 passed, 1 xfailed in 29.96s
```

New: 15 aggregate tests, 15 leakage, 10 performance, 12 drift, 8 fairness,
plus the 5 existing base-feature tests. The four gates run end to end with the
workflow's flags:

```
Gate 1  RESULT: no leak detected
Gate 2  RESULT: PASS (PR-AUC 0.1590, AUC 0.7788)
Gate 3  RESULT: PASS with warnings          (card_chargeback_rate PSI 0.2499)
Gate 4  RESULT: PASS (report written; 13 slice(s) marked for review)
model card present
```

**Verified in the failing direction.** `test_leakage.py` runs Gate 1 on the
notebook definition: `RESULT: LEAK in card_chargeback_rate`, exit 1 with
`--fail-on-leak`, 4,000 / 6,708 / 7,188 rows changed at the three cutoffs and
5 of 5 on the own-outcome probe. `test_drift.py` shows the naive quantile PSI
collapses to one bin on the zero-inflated feature (PSI 0) where the gate's
binning reports it. `test_performance.py` shows the leaky frame clears any
floor (PR-AUC 0.35, AUC 0.90) so a reader sees why the gates are ordered.

Notebook 03 executed in place (nbconvert, 10s); every table in this
description is an output in that file.

---

## Confidence

**High on the root cause.** Four independent shadow numbers (AUC, PR-AUC, two
monthly AUCs) and both reported feature statistics reproduce to four decimals
from one fitted object and one mechanism.

**Gaps a reviewer should know about:**

- The champion comparison is against `base.py`'s feature set, not the deployed
  `fraud-v2` (follow-up 1). They agree to 0.002 AUC on this holdout.
- The serving cutoff (fresh vs nightly) is inferred from the shadow stats, not
  confirmed with platform (M2). The two differ by 0.0005 AUC.
- Gate 3's 0.2499 is explained but not comfortable (M1).
- All of this is synthetic data by design. The mechanism is general; the
  magnitudes are this generator's.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
