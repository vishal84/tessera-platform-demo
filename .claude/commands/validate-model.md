---
description: Validate a model or feature set for leakage, drift and fairness before it ships
argument-hint: <notebook, module or model to validate>
allowed-tools: Read, Grep, Glob, Bash, Write, Task
---

Validate: **$1**

Use the `model-validator` agent.

Start from the assumption that a large unexplained improvement is a bug.

## 1. Leakage first

For every feature, answer the question that matters: **when does this value
become known in the real world?** Not when it appears in the table.

Pay particular attention to:
- aggregates computed with a `groupby` over the full frame
- anything derived from `chargeback_filed_at`, `is_fraud`, or another outcome
- features refreshed by a batch job (what is their staleness at serving time?)
- the train/test split — is it temporal?

## 2. Quantify anything you find

Do not stop at "this looks leaky". Build the point-in-time-correct version,
retrain, and report both numbers side by side. The honest lift is the finding.

## 3. Then the rest

- Is the metric right for the base rate? For ~3% positives, PR-AUC over AUC.
- Performance by time slice, not just aggregate.
- Drift: PSI between training and recent data.
- Fairness: per-slice performance across protected and proxy attributes.

## 4. Report

Lead with the finding that changes what the team should do. Give the evidence
and the number. Say clearly whether this is safe to ship.

If it is sound, say so, and say what you checked.
