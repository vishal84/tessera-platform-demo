---
description: Implement a feature through the full Tessera path — plan, tests, implementation, PR
argument-hint: <what to build>
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
---

Implement: **$1**

## Before writing code

Read the code you are about to change. Find the existing pattern and follow
it — a feature that looks like the rest of the codebase is a feature the team
can maintain.

If this touches money or the ledger, the `ledger-invariants` skill applies.
Work out the postings before writing the implementation.

## Order of work

1. **Plan.** State what changes, in which files, and why. If the change spans
   the API, the ledger and a migration, say how they fit together.
2. **Tests first**, where the expected behaviour is clear. Check for an
   existing `xfail` describing what you are about to build.
3. **Implement**, smallest coherent change that does the job.
4. **Run the tests.** `uv run pytest`. All of them, not just the new ones.
5. **Check the seams** — what breaks elsewhere? Grep for callers.

## Constraints that will be enforced whether you follow them or not

- `.env`, key material and `infra/prod/` are blocked by the secrets guardrail.
  New config goes to `.env.example` plus `docs/config.md`.
- No cardholder data in source, tests or logs. The PII scanner runs on every
  write.
- Money is integer minor units.
- Every outbound call has a timeout; every retry has backoff and jitter.

## Finish

Branch, commit with a conventional-commit message, open a PR. The description
says what changed, why, and what a reviewer should look at closely.

Do not merge your own PR.
