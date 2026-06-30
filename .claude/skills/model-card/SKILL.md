---
name: model-card
description: Write a model card for MRM review before a model ships. Use when documenting a fraud, credit, or behavioural model, or when preparing an SR 11-7 / model risk submission.
---

# Model card

Every model that makes a decision about a customer needs one before it ships.
Model Risk Management reviews it under SR 11-7. Write it for a reviewer who is
technically literate but did not build the model.

## Required sections

**Purpose and scope** — what decision this model makes, for whom, and what it
must not be used for. Scope creep into an unvalidated use is a common finding;
state the boundary explicitly.

**Training data** — source, date range, row count, base rate. Say how the
train/test split was made. For anything time-ordered, the split is temporal and
you state the cutoff. A random split on time-ordered data is a finding on its
own.

**Features** — every feature, and for each one: **when its value becomes
known**. This is the column reviewers read first, because it is where leakage
hides. A feature derived from an outcome that arrives weeks later cannot be
used to predict that outcome.

Flag explicitly any feature that:
  - is an aggregate over historical data (state the `as_of` cutoff used)
  - is refreshed on a batch schedule (state the staleness at serving time)
  - could act as a proxy for a protected characteristic

**Performance** — the metric appropriate to the problem, on a genuinely held
out set. For imbalanced problems report PR-AUC and recall at the operating
threshold, not AUC alone. Include performance by time slice, not just
aggregate — a model that only works on average is a model that stopped working
in month three.

**Fairness** — per-slice performance across protected and proxy attributes.
Report the numbers even where they are uncomfortable; a reviewer who finds an
unreported disparity distrusts everything else in the document.

**Limitations and failure modes** — where this model is known to be weak, what
happens when a feature is missing or stale, and what it does on populations
under-represented in training. Be concrete. "May underperform on thin-file
applicants" is worth more than a paragraph of hedging.

**Monitoring plan** — what is watched in production, at what thresholds, and
who is paged. Include feature drift and score distribution, not just accuracy,
because label feedback arrives far too late to be an alarm.

**Decisions and explanations** — for credit models, the mapping from model
output to adverse-action reason codes, and the evidence that those codes
reflect what actually drove the decline. A reason code that is not the real
reason is a regulatory problem (ECOA/Reg B, FCRA §615).

## Tone

State what you know and what you do not. A model card that reads as advocacy
gets a harder review than one that names its own weaknesses first — and it
should, because the reviewer now has to find the weaknesses themselves.
