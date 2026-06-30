---
name: incident-postmortem
description: Write a blameless postmortem after an incident is mitigated. Use when documenting root cause, writing up an INC-, or producing the write-up that accompanies an incident fix PR.
---

# Blameless postmortem

A postmortem exists so the organisation learns something it can act on. It is
not a report card, and it is not a formality attached to a fix.

## Blameless means specific, not vague

Blameless does not mean avoiding detail. Name the commit, the config value,
the missing timeout. Do not name the person, and do not imply one.

- Not: "the engineer forgot to raise the connection limit"
- Not: "a mistake was made in the settlement job configuration"
- Yes: "`batch_size` was raised from 500 to 5000 in `4c1e90d`. The job holds a
  database connection per batch, and nothing in the repository connected batch
  size to pool capacity, so the change was reviewed as a throughput tuning
  knob."

The last framing is more useful *and* kinder. If a change could take down
production and nothing stopped it, that is a property of the system, not of
the person who made the change.

## Structure

**Summary** — three sentences. What broke, for how long, and who was affected.
Someone who reads only this should be able to decide whether to read on.

**Impact** — in the units the business uses. Declined authorizations,
merchants affected, revenue at risk, customer reports. Not just error rates.

**Timeline** — timestamped, from the change that introduced the risk through
to resolution. Include detection time and the gap between the change and the
alert; that gap is usually itself a finding.

**Root cause** — the specific change or condition, with the evidence that
identifies it.

**Contributing factors** — the latent weaknesses that let a small change
become an incident. These matter more than the trigger. A system where one
config change causes a 30% authorization failure has several.

**What went well** — genuinely. Fast detection, a runbook that worked, a
useful dashboard. Teams that only catalogue failures stop writing these.

**Action items** — each with an owner and a due date. Distinguish:
  - *Prevent* — stop this specific cause recurring
  - *Detect* — find it faster next time
  - *Mitigate* — reduce blast radius when something like it happens again

A postmortem whose only action item is "fixed the bug" has not been thought
about. The bug was the trigger; the system let it through.

## Five whys, used properly

Keep asking until you reach something structural rather than a person or a
single line of code.

> Settlement fell behind → the job stalled on connection acquisition → the
> pool was exhausted → each batch holds a connection and batches got ten times
> larger → **nothing tied batch size to pool capacity, so a throughput change
> was reviewed without anyone seeing it was a concurrency change.**

The last line is the finding. Everything before it is mechanism. Stop when you
reach something structural — a missing check, an undocumented coupling, a
signal nobody was watching — and not before.

## Length

One page for a SEV-2. Two for a SEV-1. Nobody reads the fourth page, so the
thinking has to happen before the writing, not during it.
