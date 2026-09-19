# Talking points

One page per seat in the room. The console is the same for all three; what
changes is what each of them is watching for.

## The SRE — "what does it do at 3am, and what stops it doing harm?"

**What you show.** The **Triage with Claude** button runs the same headless
command the incident workflow runs: same prompt, same tool allowlist, same
turn budget, read from `claude-incident-fix.yml` at run time. **Show the
command** puts the argv on screen. The feed is every tool call it makes.

**The line.** _It correlated three artifacts from three systems — a metrics
inflection, a deploy record, a one-line diff — and then proved the hypothesis
by reproducing the incident from the shipped config. That is the part of
incident response that takes a human twenty minutes and a Slack thread._

**The containment, in order.**

1. The tool allowlist is enumerated, not open. The amber `allowlist` rows in
   the feed are denials happening — there is no approval surface, so anything
   not listed is refused automatically.
2. The hooks ran on every write. The footer count says how many; the
   Guardrails page has each one.
3. The output is a branch and a PR. The job holds no deployment permission,
   and its last step re-runs both hooks and fails the run if `.env` or
   `.claude/hooks/` moved. Here a human pressed **Merge**.

**Do not say "`main` is protected"** unless you actually enabled branch
protection on your own remote (`demo/PUSH_AND_VERIFY.md` §4 — it needs GitHub
Pro or a public repository, and returns 403 on a private free-tier repo). The
three points above are true either way; that fourth one is a property of your
GitHub settings, not of this repository, and an SRE may well ask to see it.

**Why it is shown locally.** The GitHub Action would produce the same PR on a
runner nobody can see. Running the identical command on this machine is the
honest way to put the automation on a screen. Push the repo and the same
button becomes `repository_dispatch` (`demo/PUSH_AND_VERIFY.md`).

**Objection: it hit the turn limit / it needed two tries.** Say so. The point
is not that it is flawless at 3am; the point is that when it is wrong, the
worst outcome is a PR nobody merges.

## The engineer — "will it respect our rules, or just my prompt?"

**What you show.** The hand-off. **Request review** puts the prompt on the
card; the SWE picks the PR up in the desktop app, in a different session, and
the first thing they hit is the guardrail: `.env` is protected, by a program
with an exit code, and the console shows the block with the badge
`desktop session`.

**The line.** _That is a hook, not a prompt. It cannot be talked out of it.
It fired from a different person's session, on the same repository, and it
logged itself._

**Then the escalations** — a shell redirect, a read — so nobody in the room
thinks it is one tool's behaviour. All three land on the Guardrails feed.

**What to notice about the fix.** Ask Claude whether the fix is separable
from the cleanup. It should say yes: the TTL restore is the fix; the timeout,
backoff and breaker are the reliability rules in `CLAUDE.md` finally being
applied. That is a review conversation, not a rubber stamp.

**Objection: "our codebase is messy".** `CLAUDE.md` and skills are how you
encode "messy for a reason". The guardrails matter more, not less, when the
codebase is not clean.

## The data scientist — "does it understand modelling, or just pandas?"

**What you show.** A number that stopped a promotion — shadow AUC below the
champion — and a notebook that does not yet explain it. Then Claude explains
it with numbers, in the notebook, and productionizes the finding through the
same gates the engineer's PR goes through.

**The two mechanisms.** Say both, in this order:

1. *Leakage.* `card_chargeback_rate` was computed over all history, including
   each row's own future chargeback. Disputes arrive 20–90 days later (median
   54). The point-in-time version of the feature is worth minus 0.0008 AUC —
   nothing.
2. *Train/serve skew.* The offline model learned a feature that is non-zero
   27% of the time; at scoring it is non-zero 14% of the time. The same model,
   meeting the served feature, scores 0.699 — below the champion. That is
   what shadow measured.

**The line.** _This is not an exotic mistake. It is the single most common way
a fraud model dies in production, and it dies quietly, six months later, when
someone finally compares backtest to booked performance. It was caught here,
before the PR, by a gate the team wrote before the code existed._

**What "productionize" means here.** Point-in-time aggregates with an `as_of`
cutoff, the four gates from `model-validation.yml` with their exact flags, a
negative fixture that proves Gate 1 catches the notebook's definition, and a
model card for MRM. The **Negative proof** button runs that test.

**Breadth, in one sentence.** Credit scoring and customer profiling ride the
same rails; credit adds adverse-action reason codes for ECOA/FCRA. Different
gates bolted on, not a second stack.
