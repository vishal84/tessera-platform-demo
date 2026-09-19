# Tessera demo — the complete guide

Everything needed to set up, rehearse, present and recover the Tessera
Financial demo. One file, five parts.

| Part | What it is | When you read it |
|---|---|---|
| [1 — Setup](#part-1--setup) | Toolchain, history, fallbacks, reset, Actions | Once per laptop (~1h 45m) |
| [2 — The argument](#part-2--the-argument) | What you are claiming and to whom | Before your first rehearsal |
| [3 — The runbook](#part-3--the-runbook) | Beat by beat, ~50 minutes | Open on stage |
| [4 — Under pressure](#part-4--under-pressure) | Recovery, questions, drills, certification | Rehearse before presenting |
| [5 — Reference](#part-5--reference) | Commands, numbers, fictional-content notes | Lookup |

**Total to go from a fresh laptop to certified: ~3h 45m.** Part 1 is once.
Parts 3–4 are rehearsed beat by beat. Part 4 is what separates someone who has
seen the demo from someone who can run it in front of a hostile room.

You are not learning a product tour. You are learning to run a fifty-minute
argument that three different skeptics can each verify from their own seat.

**Conventions in this document.** Prompts in `> blockquotes` are typed verbatim
into the desktop app. Lines in _italics_ are what to say out loud. **[VARIABLE]**
marks a beat where Claude's exact output differs run to run — the shape holds,
the words will not. Button labels are in **bold** exactly as they appear in the
console.

---

# Part 1 — Setup

## 1.1 Prerequisites

| Tool | Why | Check |
|---|---|---|
| Claude Code, logged in | the demo | `claude -p "reply with the word OK"` prints `OK` |
| `uv` | Python deps, JupyterLab | `uv --version` |
| Node 20+ | builds the console UI (`web/`) | `node --version` |
| `git` | history is part of the incident | `git --version` |
| `gh` (optional) | only for the live GitHub Actions beats | `gh auth status` |

All at once:

```bash
claude -p "reply with the word OK" && uv --version && node --version && git --version
```

`claude -p` must print `OK`. Note that `claude --version` succeeds even when you
are logged out, so it is **not** a valid check — this one is.

Python 3.11+ for the project. The guardrail hooks run under whatever `python3`
is on your `PATH` (they are stdlib-only and need 3.10+). No Docker, no database,
no network calls beyond Claude itself — every beat runs locally, on purpose.
A demo that depends on someone else's uptime is a demo that fails in front of an
audience. Say this out loud when you present; an SRE in the room will respect
that you made the choice deliberately.

## 1.2 First run

> [!WARNING]
> **Steps 2 and 3 below take 10–20 minutes of download and build time.** Do not
> sit and watch them. Start them, then read [Part 2](#part-2--the-argument) and
> skim `CLAUDE.md` in a second terminal session. Come back when the prompt
> returns.
>
> ```bash
> # macOS Terminal or iTerm: Cmd-T for a new tab, then
> cd ~/path/to/tessera-platform && claude
> ```
> In the Claude Code desktop app, use the **+** button (or Cmd-N) to open a
> second session on the same folder. Both sessions share the same `.claude/`
> rules — which is itself the point you make in [beat 1.5](#15-the-engineer-picks-it-up-6-min--desktop-app-variable).

1. Clone your team's copy of the demo repository — the one carrying the
   `demo-base` tag — and enter it:

   ```bash
   git clone https://github.com/<your-org>/tessera-platform.git
   cd tessera-platform
   ```

   A normal clone brings the tags down with it, which is all the setup the git
   side needs. **Never run `git init`, and never delete `.git`**: the commit
   history is the evidence the whole SRE beat is built on. [Section 1.3](#13-verify-the-demo-history) checks it.

2. Install Python dependencies, including the notebooks group JupyterLab lives in:

   ```bash
   uv sync --all-groups
   ```

3. Build the ops console front end:

   ```bash
   npm --prefix web ci && npm --prefix web run build
   ```

4. Open `CLAUDE.md` and read the four rule blocks — money, security,
   reliability, conventions. **The result:** you now know where the rules the
   demo enforces actually live. This is the `CLAUDE.md` feature of Claude Code:
   project memory loaded into every session automatically, for every person,
   without anyone remembering to paste it into a prompt. You will reference it
   in [beat 1.5](#15-the-engineer-picks-it-up-6-min--desktop-app-variable).

5. Confirm the readiness checks run:

   ```bash
   ./demo/reset-demo.sh --check
   ```

   You want green checks and `Ready.` Two warnings are expected until you record
   the fallbacks in [1.4](#14-record-the-fallbacks): `no golden recording` and
   `no executed notebook fallback`.

**Talking points you are earning here (for later, not now):** the whole thing is
one repository. There is no second stack, no sidecar service, no "and then you'd
integrate it with…". The agent reads the repo the same way your engineers do.

## 1.3 Verify the demo history

The incident in [use case 1](#use-case-1--sre-and-swe-collaborate-on-inc-4412--26-min)
is solved by correlating a deploy record against `git log`. The commit history
*is* the evidence, so before anything else, confirm it arrived intact.

**You are not building anything here.** The synthetic history and the
`demo-base` tag were authored once, by whoever set up your team's repository,
and they came down with your clone. This is three commands that all read.

> [!WARNING]
> **Never run `./demo/build_history.sh`.** It is the authoring step for the
> person who originally created the demo, and it begins by deleting `.git` —
> which on your clone destroys the `origin` you cloned from, the `demo-base`
> tag, and your reflog. The script refuses to run without `--force` for exactly
> this reason, and nothing in your setup ever needs it.
>
> `reset-demo.sh` is the reset. `build_history.sh` is not a reset, and it is not
> yours to run.

1. Confirm the anchor tag came down with the clone. It is what every reset
   rewinds to, so nothing works without it:

   ```bash
   git tag --list demo-base
   ```

   You want one line back: `demo-base`. If it is empty, the repository you cloned
   has not pushed its tag — ask whoever maintains it to run
   `git push origin demo-base`. Do **not** reach for `build_history.sh`.

2. Confirm the trap is armed:

   ```bash
   git show --stat 4b56e1d && git show b745a5a
   ```

3. Confirm you are starting from the anchor:

   ```bash
   git log --oneline -1 demo-base && git status --short
   ```

**The result:** `4b56e1d` is a one-line docstring change — the revision the
deploy record names — and `b745a5a` is the one-line TTL change that actually
caused the incident. Both present, a clean tree, and `demo-base` resolving means
every later beat will work. You did all of this with reads; the demo's evidence
is something you inspect, never something you generate.

**Talking points you are earning here:**

- The deploy record for the 14:02 deploy names revision `4b56e1d`, which is a
  one-line docstring change. The actual cause is `b745a5a`, which that deploy
  also carried. **This trap is the whole reason the triage beat is impressive** —
  a naive responder reads the deploy record, reads the diff, finds nothing, and
  stalls. Claude widens to `git log -- services/risk_gateway/` and finds the
  other three commits that deploy shipped.
- When someone asks "is the incident staged?", the honest answer is: the
  *scenario* is constructed, the *mechanism* is not. `git show b745a5a` is a real
  one-line diff and the metrics are generated by an actual capacity model.

## 1.4 Record the fallbacks

Three beats in the demo are live Claude runs. Live runs are the point — and live
runs sometimes wander. This records a known-good version of each one so that
when a run goes long in front of an audience, you press a button instead of
apologising.

**You will use these. Plan on it.** The safe default for a tight room is to play
the recording from the start.

> [!WARNING]
> **Step 2 is a real headless Claude run: 8–12 minutes and a few dollars of API
> spend. Steps 4 and 5 are 6–10 minutes each.** Total unattended time is around
> 35 minutes.
>
> Start step 2, then go read [Part 3](#part-3--the-runbook) in a second session.
> Note that `reset-demo.sh` refuses to run while a headless run is active — so do
> not try to reset from the second session until step 2 finishes.

1. Start the demo services and leave them running:

   ```bash
   ./demo/up.sh
   ```

2. In a second terminal, on a clean `main`, record the golden triage run:

   ```bash
   ./demo/record-golden-run.sh
   ```

   It runs one real headless triage (8–12 minutes) and copies the stream, the PR
   description and the branch patch into `demo/recordings/triage-INC-4412/`. The
   console's **Play recording** button plays it back at 1–16×, and playing it
   restores the branch and PR so the beats after it still work.

3. Open the ops console at `http://localhost:8765`, go to **Incidents** and press
   **Play recording** at **4×** to confirm the playback works and restores the PR.

4. Record the notebook fallback. In the desktop app, run **Prompt 1** from the
   **Models** page once, let it finish, then:

   ```bash
   cp ml/notebooks/03_v3_shadow_investigation.ipynb \
      demo/recordings/03_v3_shadow_investigation.executed.ipynb
   ```

5. Record the productionize fallback:

   ```bash
   git checkout -b ml/tess-2310-validation-gates
   # run Prompt 2 in the desktop app and let it commit on this branch
   git format-patch --stdout main..HEAD > demo/recordings/ml-tess-2310.patch
   git checkout main && git branch -D ml/tess-2310-validation-gates
   ```

6. Record the data-scientist beat as a replay (recommended). The **Models** page
   runs the same headless machinery the **Incidents** page does, so
   [2.2](#22-investigate-6-min--desktop-app-variable) and
   [2.3](#23-productionize-6-min--desktop-app-variable) can be recorded once and
   replayed as a single streamed run, rather than restored from the two flat
   files above. Start the services with the model pinned and the budget raised:

   ```bash
   TESSERA_CLAUDE_MODEL=claude-fable-5-1 TESSERA_MAX_BUDGET_USD=40 ./demo/up.sh
   ```

   On **Models**, press **Investigate with Claude**. This is a longer and more
   expensive run than the triage one — budget 25–45 minutes and roughly $12. When
   it finishes, promote it:

   ```bash
   cp -R .tessera/runs/$(ls -t .tessera/runs | head -1) \
      demo/recordings/validate-fraud-v3-candidate
   ```

   Then fold it into the anchor tag, **or the next reset deletes it**:

   ```bash
   git add demo/recordings/validate-fraud-v3-candidate && git commit -m "chore(demo): golden model recording"
   ./demo/reset-demo.sh --adopt-base
   ```

   `reset-demo.sh` hard-resets `main` to `demo-base` and then runs `git clean -qfd`,
   so anything under `demo/` that is not in that tag is gone on the next reset.
   `--adopt-base` is what carries it across. `--check` then reports `golden model
   recording present`.

7. Commit the recordings: `./demo/build_history.sh` adds them in a final commit
   of its own. (Authoring step only — see the warning in [1.3](#13-verify-the-demo-history).)

**The result:** `./demo/reset-demo.sh --check` now reports `golden triage
recording present`, `executed notebook fallback present` and
`productionized-branch fallback present`. You were using **Claude Code headless
mode** (`claude -p`) for the recording and the **desktop app** for the two
interactive beats — same repository, same `.claude/` rules in both.

**Talking point you are earning here:** when you play a recording, **say so, out
loud, every time**. The console shows a full-width `RECORDING` banner in a colour
nobody can miss. Presenting a recording as a live run is the kind of thing that
gets noticed, and it costs you the room.

## 1.5 Starting the demo, and the reset ritual

This is the two-command ritual you run before every single demo, forever. Learn
it now so it is muscle memory rather than something you look up while an audience
watches.

```bash
./demo/reset-demo.sh && ./demo/up.sh
```

`up.sh` starts the ops console on `http://localhost:8765` and JupyterLab on
`http://localhost:8888/lab?token=tessera`, builds `web/dist` if it is stale, and
checks that headless Claude answers. `Ctrl-C` stops both. Ports:
`TESSERA_CONSOLE_PORT`, `TESSERA_JUPYTER_PORT`.

`up.sh` also sets `TESSERA_PR_PROVIDER=local`, which keeps the console's pull
requests in `.tessera/prs/` where `reset-demo.sh` can clear them. Without it the
console reads `gh pr list` instead, and since GitHub cannot delete a merged pull
request, every run would leave one on the Incidents tab for the next run to open
with. The remote is still used for the GitHub Actions beats.

`reset-demo.sh` backs up uncommitted work to a timestamped patch outside the
repository (it deliberately does **not** use `git stash` — see the comment in the
script), hard-resets `main` to the `demo-base` tag (the merge in
[beat 1.6](#16-merge-and-recover-2-min--incidents) moves `main`; only a hard
reset undoes it), deletes every other branch, clears the console's runtime state
under `.tessera/`, regenerates the synthetic data, notebooks, incident evidence
and model registry, re-syncs the commit SHAs quoted in this document, and re-runs
the readiness checks. It refuses to run while a headless run is active.

Arguments are exactly `--check`, `--restore-notebook`, `--restore-gates`,
`--help` or nothing; anything else prints usage and exits.

> [!WARNING]
> **`reset-demo.sh` is the only reset.** If a run leaves the repository in a
> state this does not fix, the answer is still this command — never
> `build_history.sh`, which deletes `.git` and would cost you your `origin`, the
> `ANTHROPIC_API_KEY` link that comes with it, the `demo-base` tag and your
> reflog.

Run the readiness check on its own first — it changes nothing:

```bash
./demo/reset-demo.sh --check
```

You want all `ok` and the final line `Ready.` The checks worth understanding,
because they are the demo's preconditions:

- `deploy record names 4b56e1d, which is NOT the cause` — the trap is armed
- `the causing commit b745a5a appears nowhere in the evidence bundle`
- `demo/ is read-denied to the agent` — the answer key stays closed
- `investigation notebook (03) is the 5-cell seed` — Claude has work to do
- `ml/validation/ absent` — the gates read NOT IMPLEMENTED until [beat 2.3](#23-productionize-6-min--desktop-app-variable)

**Talking points you are earning here:** none — this is stagecraft. But knowing
that the reset regenerates the evidence bundle from a generator is what lets you
answer *"is the incident staged?"* honestly and immediately.

## 1.6 Making the Actions beats live (optional, recommended)

Two beats — [1.4](#14-the-pull-request-2-min--incidents) (automated PR review)
and [2.4](#24-the-contract-2-min) (alert-triggered triage) — show workflow files
and captured output because nothing is pushed yet. This converts them to live
runs. About fifteen minutes.

Everything else in the demo runs locally and needs none of this. You can skip
this entire section and the demo still works. But being able to say *"the same
command runs in Actions, here it is running"* is worth the fifteen minutes.

**Talking points you are earning here:**

- `.github/workflows/claude-incident-fix.yml` is genuinely interesting to read
  aloud. The permissions block grants `contents: write` — enough to push a branch
  — and nothing that would let the job deploy. Read the last step too: it runs
  `if: always()`, re-runs both hook selftests, and fails the run if `.env` or
  `.claude/hooks/` moved. *The guardrails are not optional just because no one is
  watching.*
- `claude-code-review.yml` runs the `payments-reviewer` subagent against every PR
  diff. That is the same subagent definition in `.claude/agents/` that a developer
  invokes locally — one definition, two surfaces.

### Steps

1. Keep the team copy as `upstream`, then create a remote you own. Prefer a
   personal account or scratch org — the repo contains a realistic-looking
   (synthetic) `.env` and an incident that never happened:

   ```bash
   git remote rename origin upstream
   gh repo create tessera-platform-demo --private --source=. --remote=origin --push
   ```

   Private is enough. The audience watches your screen, not the repo.

2. Push the anchor tag to your own remote too. `gh repo create --push` sends
   branches, not tags, and without this a fresh clone of *your* copy cannot reset:

   ```bash
   git push origin demo-base
   ```

3. Add the API key that pays for the Actions runs. Scope it to this repository:

   ```bash
   gh secret set ANTHROPIC_API_KEY
   ```

4. Install the GitHub app so `@claude` mentions and the review workflow can act
   on PRs. Run `claude`, then `/install-github-app`.

5. Decide on branch protection — see the warning below — then run the check so
   you know which state you are in.

6. Verify the review beat end to end by pushing a deliberate PCI violation:

   ```bash
   git checkout -b demo/verify-review
   cat >> services/payments_api/service.py <<'EOF'

   def _debug_capture(card_number: str) -> None:
       logger.info("capturing card %s", card_number)  # reviewer should catch this
   EOF
   git add -A && git commit -m "chore: temporary debug logging"
   git push -u origin demo/verify-review && gh pr create --fill
   ```

   Two things must happen: CI fails on the cardholder-data check, and the Claude
   review posts an **inline comment on that specific line**.

7. Verify the triage beat — fire the dispatch:

   ```bash
   gh workflow run claude-incident-fix.yml -f incident_id=INC-4412
   gh run watch
   ```

   It should open a PR. Confirm it did **not** push to `main`.

8. Clean up:

   ```bash
   git checkout main && git branch -D demo/verify-review
   git push origin --delete demo/verify-review
   ```

**The result:** you have proven the guardrails run in CI, not just locally. This
used **Claude Code GitHub Actions** (`claude-code-action`) plus the **subagent**
and **hook** definitions checked into the repo — the identical
`.claude/hooks/pii_scan.py` that runs in an interactive session runs as a CI step
in `ci.yml`.

### Branch protection — only if your plan allows it

> [!WARNING]
> **Branch protection needs GitHub Pro or a public repository.** Step 1 above
> creates a *private* repo, so on a free-tier account both the protection API and
> the rulesets API return **403 — "Upgrade to GitHub Pro or make this repository
> public."**
>
> **Never say "`main` is protected in Actions" without checking.** It is the one
> containment claim in this demo that depends on your GitHub settings rather than
> on anything in the repository, and it is the one a skeptical SRE is most likely
> to ask to see.

```bash
gh api -X PUT repos/:owner/tessera-platform-demo/branches/main/protection \
  -f "required_pull_request_reviews[required_approving_review_count]=1" \
  -F "enforce_admins=false" \
  -F "restrictions=null" \
  -F "required_status_checks=null"
```

If it succeeds, verify in Settings → Branches that direct pushes to `main` are
blocked. Being able to say "try it yourself" when someone asks is worth two
minutes. Check which state you are in before you present:

```bash
gh api repos/{owner}/{repo}/branches/main/protection >/dev/null 2>&1 \
  && echo "protected — you may say so" \
  || echo "NOT protected — do not claim it"
```

If it returns 403 you have three options: make the repo public (it is entirely
synthetic — see [What is fictional](#52-what-is-fictional)), use an account with
Pro, or leave it off. **Leaving it off is fine, but then do not claim it.** The
containment that holds without it is real, and it is what the rest of this
document leads with: the enumerated tool allowlist, the hooks on every write, no
deployment permission in the job, and a final workflow step that re-runs both
hooks and fails the run if a protected path moved. Those are properties of the
repository, which makes them the stronger argument anyway.

### The console after you push

The console picks a pull-request provider at startup: `local` when there is no
remote (PRs are `.tessera/prs/*.md` plus a branch), `github` when `git remote`
and `gh auth status` both succeed. With the `github` provider:

- **Triage with Claude** keeps `Bash(gh pr create:*)` in the allowlist, so the
  headless run opens a real pull request and the card links to it.
- **Merge** runs `gh pr merge --merge` and then refreshes `main` from origin.
- `claude-code-review.yml` reviews the PR on GitHub; the console does not
  duplicate that, it links to it.

Everything else — the feed, the audit trail, the timeline, the gates — is
unchanged. `GET /api/health` reports which provider is active.

### Resetting between runs

Live runs leave PRs and branches behind:

```bash
gh pr list --json number --jq '.[].number' | xargs -n1 gh pr close --delete-branch
./demo/reset-demo.sh
```

### If you would rather not push at all

Perfectly reasonable, and the demo still works. Show the workflow files —
`claude-incident-fix.yml` is genuinely interesting to read, especially the
permissions block and the final guardrail step — and walk the captured output in
`demo/expected-output/`.

Say plainly that it is captured output. The audience is evaluating the shape of
the workflow, not whether a runner executed it in front of them.

---

# Part 2 — The argument

## 2.1 What you are demonstrating

**The claim.** Three people who share almost no daily context work in one
repository, under one set of rules that are *executable* — and those rules hold
whether a human is watching or not.

**The scenario, in one paragraph.** Tessera Financial is a fictional card issuer
(PCI-DSS Level 1, SOC 2 Type II) where every card authorization blocks on one
synchronous fraud-model call at ~400 requests a second, and that call fails
closed — no decision means a decline. The demo runs two failures of that same
dependency. **INC-4412** is the loud one: a deploy labelled a memory optimisation
set the risk gateway's cache TTL to zero, the cache had been absorbing ~77% of
scoring calls, and the resulting 2.7× overload plus retry amplification dropped
authorization success from 99.9% to 71% — roughly 41,300 good authorizations
declined across 2,184 merchants. **TESS-2310** is the quiet one: a fraud model
that scored 0.906 AUC offline scored 0.699 in shadow, below the 0.778 champion,
because its strongest feature was computed with a `groupby` over the whole table
and so handed every row its own chargeback — a label that arrives 20 to 90 days
after the transaction it describes. One pages someone at 3am; the other would
have shipped and died silently six months later.

**The three surfaces you will use, and why each one is there:**

- **Claude Code CLI, headless (`claude -p`)** — the 3am story. No human, no
  approval prompt, an enumerated allowlist. This is the one SREs care about.
- **Claude Code desktop app** — the working session. Same repository, same
  `.claude/` rules, different person. This is where the guardrail collision lands
  and where the notebook work happens.
- **GitHub Actions** — the same rules at the door. Proves the guardrails are not
  a local-machine courtesy.

The opening line, to be delivered over the **Overview** page:

> _Everything you see today runs in one repository. The SRE, the engineer and
> the data scientist work in the same tree, under the same rules. Those rules
> live in `.claude/` — and they are code, not suggestions. The console is how you
> watch them hold._

The personas are colour-coded on every button and every timeline node — **SRE**,
**SWE**, **Data scientist**, **Claude**. The timeline rail is the spine of the
story: it shows the hand-offs.

## 2.2 Who is in the room

| Seat | The question they are actually asking | The beat that answers it |
|---|---|---|
| **SRE** | "What does it do at 3am, and what stops it doing harm?" | [1.3](#13-watch-it-work-79-min--incidents-variable) — headless triage with an enumerated tool allowlist |
| **SWE** | "Will it respect our rules, or just my prompt?" | [1.5](#15-the-engineer-picks-it-up-6-min--desktop-app-variable) — the hook fires and cannot be talked out of it |
| **Data scientist** | "Does it understand modelling, or just pandas?" | [2.2–2.3](#22-investigate-6-min--desktop-app-variable) — leakage found with numbers, then shipped through gates |

## 2.3 Talking points by seat

One page per seat in the room. The console is the same for all three; what
changes is what each of them is watching for.

### The SRE — "what does it do at 3am, and what stops it doing harm?"

**What you show.** The **Triage with Claude** button runs the same headless
command the incident workflow runs: same prompt, same tool allowlist, same turn
budget, read from `claude-incident-fix.yml` at run time. **Show the command** puts
the argv on screen. The feed is every tool call it makes.

**The line.** _It correlated three artifacts from three systems — a metrics
inflection, a deploy record, a one-line diff — and then proved the hypothesis by
reproducing the incident from the shipped config. That is the part of incident
response that takes a human twenty minutes and a Slack thread._

**The containment, in order:**

1. The tool allowlist is enumerated, not open. The amber `allowlist` rows in the
   feed are denials happening — there is no approval surface, so anything not
   listed is refused automatically.
2. The hooks ran on every write. The footer count says how many; the Guardrails
   page has each one.
3. The output is a branch and a PR. The job holds no deployment permission, and
   its last step re-runs both hooks and fails the run if `.env` or
   `.claude/hooks/` moved. Here a human pressed **Merge**.

**Do not say "`main` is protected"** unless you actually enabled branch
protection on your own remote ([1.6](#branch-protection--only-if-your-plan-allows-it)).
The three points above are true either way; that fourth one is a property of your
GitHub settings, not of this repository, and an SRE may well ask to see it.

**Why it is shown locally.** The GitHub Action would produce the same PR on a
runner nobody can see. Running the identical command on this machine is the
honest way to put the automation on a screen. Push the repo and the same button
becomes `repository_dispatch`.

**Objection: it hit the turn limit / it needed two tries.** Say so. The point is
not that it is flawless at 3am; the point is that when it is wrong, the worst
outcome is a PR nobody merges.

### The engineer — "will it respect our rules, or just my prompt?"

**What you show.** The hand-off. **Request review** puts the prompt on the card;
the SWE picks the PR up in the desktop app, in a different session, and the first
thing they hit is the guardrail: `.env` is protected, by a program with an exit
code, and the console shows the block with the badge `desktop session`.

**The line.** _That is a hook, not a prompt. It cannot be talked out of it. It
fired from a different person's session, on the same repository, and it logged
itself._

**Then the escalations** — a shell redirect, a read — so nobody in the room
thinks it is one tool's behaviour. All three land on the Guardrails feed.

**What to notice about the fix.** Ask Claude whether the fix is separable from
the cleanup. It should say yes: the TTL restore is the fix; the timeout, backoff
and breaker are the reliability rules in `CLAUDE.md` finally being applied. That
is a review conversation, not a rubber stamp.

**Objection: "our codebase is messy".** `CLAUDE.md` and skills are how you encode
"messy for a reason". The guardrails matter more, not less, when the codebase is
not clean.

### The data scientist — "does it understand modelling, or just pandas?"

**What you show.** A number that stopped a promotion — shadow AUC below the
champion — and a notebook that does not yet explain it. Then Claude explains it
with numbers, in the notebook, and productionizes the finding through the same
gates the engineer's PR goes through.

**The two mechanisms.** Say both, in this order:

1. *Leakage.* `card_chargeback_rate` was computed over all history, including
   each row's own future chargeback. Disputes arrive 20–90 days later (median
   54). The point-in-time version of the feature is worth **−0.0008 AUC** — say
   *"within noise of zero"*, not *"exactly zero"*, because the number on screen
   is negative.
2. *Train/serve skew.* The offline model learned a feature that is non-zero
   **27.4%** of the time in training; at scoring it is non-zero **14.2%** of the
   time. The same model meeting the served feature scores **0.699** — below the
   champion. That is what shadow measured.

**The line.** _This is not an exotic mistake. It is the single most common way a
fraud model dies in production, and it dies quietly, six months later, when
someone finally compares backtest to booked performance. It was caught here,
before the PR, by a gate the team wrote before the code existed._

**What "productionize" means here.** Point-in-time aggregates with an `as_of`
cutoff, the four gates from `model-validation.yml` with their exact flags, a
negative fixture that proves Gate 1 catches the notebook's definition, and a
model card for MRM. The **Negative proof** button runs that test.

**Breadth, in one sentence.** Credit scoring and customer profiling ride the same
rails; credit adds adverse-action reason codes for ECOA/FCRA. Different gates
bolted on, not a second stack.

## 2.4 Screen layout

Left half of the projector: the console in a browser (`http://localhost:8765`).
Right half: the Claude Code desktop app, opened on the **repository root** —
`.claude/settings.json` resolves the hooks relative to it, and **starting in a
subdirectory means no guardrails at all**, which removes the spine of use case 1.
JupyterLab opens in a browser tab when you need it. Dark theme is the default;
**Switch to light** is in the sidebar if the room is bright.

---

# Part 3 — The runbook

**~50 minutes.** Two use cases, one repository, one set of guardrails, told by
clicking through the **Tessera Ops Console** with the Claude Code desktop app
open beside it.

Before you start: `./demo/reset-demo.sh` → `Ready.`, then `./demo/up.sh`.

---

## Opening — 4 min

**Overview** page. Production tiles are red: auth success **70.8%**, p99
**8.50s**, fraud-model utilization **7.22×**, cache hit **0%**. The pill top
right says `production degraded · main@…`.

> _Tessera issues cards and moves money. PCI Level 1, SOC 2. About four hundred
> authorizations a second. Right now the authorization path is degraded, and
> everything on this screen is computed from what `main` would actually run —
> not from a mock._

Do not explain the incident yet. Click **Guardrails**. Point at the three columns
without dwelling:

| | |
|---|---|
| Deny list | the agent cannot even *read* `.env`, key material or `demo/` |
| Hooks | two programs with exit codes — one runs before every write, one after |
| The same checks at the door | the identical scripts run in GitHub Actions |

> _A hook is a program with an exit code. It cannot be talked out of it, and it
> runs the same at 2pm with an audience and at 3am with nobody awake. The audit
> trail underneath is every decision those hooks made. Right now it is empty. It
> will not stay empty._

**The result:** the audience has been shown an empty audit feed and told it will
fill. Everything after this is that promise being kept. You have previewed three
Claude Code features at once — **permissions**, **hooks**, and the **Actions**
symmetry — without explaining any of them.

---

## Use case 1 — SRE and SWE collaborate on INC-4412 · ~26 min

### 1.1 The incident day (2 min) — **Overview**

Press **Replay 13:30 → 14:40**. The four charts replay the incident-day telemetry
at ten minutes a second; the deploy markers pass; at **14:11** the Alerting card
turns critical and the timeline gets its first node, `alert_fired`, tagged **SRE**.

> _Watch the second panel. The cache hit rate falls off a cliff at 14:03, one
> minute after a deploy — and load on the fraud model goes up twelve times while
> authorization volume does not move. Everything else on this screen is a
> consequence of that._

Press **Open INC-4412 →** on the Alerting card.

### 1.2 Hand it to the automation (2 min) — **Incidents**

The header says `SEV-2 · open — no owner`. Click through the **Evidence bundle**
tabs: **deploys** first.

> _Four deploys that day. The one on the risk gateway went out at 14:02 and the
> deploy record names revision `4b56e1d`. Hold that thought._

Press **Show the command** on the Triage card.

> _This is what the SRE is about to run. The prompt, the tool allowlist and the
> turn budget are read from `claude-incident-fix.yml` at run time — the same file
> the PagerDuty webhook triggers. The console cannot drift from the automation it
> stands in for._

Press **Triage with Claude** (tagged **SRE**). The pill turns to `Claude
triaging`, the timeline gets `triage_started`, and the phase stepper lights up.

### 1.3 Watch it work (7–9 min) — **Incidents** **[VARIABLE]**

**What makes this land is that you are not driving.** There is no human in the
loop, no approval dialog, and no way to steer it mid-run. That is the 3am story.

You narrate; the feed does the work. Every tool call appears as a row with an
`ok` / `error` / `not allowed` pill; narration appears as text blocks. Point at
these as they arrive:

| Phase | What to say |
|---|---|
| **Evidence** — `Read ops/incidents/INC-4412/…` | _It reads all five files before forming a hypothesis. That is in the command, not in the model._ |
| **Correlate** — `git show 4b56e1d` | _The deploy record named a docstring change. One line, no behaviour. This is the trap: a deploy ships whatever is at HEAD, and HEAD is not the cause._ |
| `git log … -- services/risk_gateway/` | _It widens to the whole set of commits that deploy carried. Three touched the gateway that day._ |
| **Prove** — `uv run python -m services.risk_gateway.simulation` | _It reproduces the incident from the shipped config: utilization 7.22, success 70.8% — the numbers in the alert. The model is reproducing the real failure, not a plausible one._ |
| **Fix** — `Edit services/risk_gateway/config.py` | _Cache TTL back to 300, a timeout on the call, backoff with jitter. The trigger was one line; what made it an incident was the call policy._ |
| **Test** — `Write …/tests/test_…py` then `uv run pytest` | _A regression test — and it checks the test fails without the fix. That is the difference between a fix and a claim._ |
| **PR** — `git checkout -b incident/INC-4412-…` | _Branch, commit, description. Never a deploy._ |

Two rows deserve a sentence the moment they appear:

- an amber **allowlist** row (`Skill`, or a `Bash` command with a redirect):
  _That tool was not on the allowlist, so it was denied automatically — nobody is
  there to approve it. It adapted._
- the footer count of **hook checks passed**: _Every one of those was the secrets
  guardrail running on a real tool call, headless._

Open **Guardrails** in a second browser tab if you like: the audit feed shows the
same checks with the badge `headless run`. It is a second thing to point at when
the main feed is quiet.

> [!WARNING]
> **A live run takes 8–12 minutes and 30–45 turns. This is the longest unattended
> stretch in the demo, and it is where you do your talking.** Do not stand in
> silence watching a feed scroll.
>
> **If it has not reached the PR phase by the eight-minute mark**, press
> **Cancel**, then **Play recording** with `golden recording` at **4×** (about two
> minutes). The banner across the top says **RECORDING** in a colour nobody can
> miss; say it out loud:
>
> > _This is a recording of the same run from earlier today, played at four times
> > speed. Everything you see it do, it did._
>
> Playing the recording restores the branch and the PR at the end, so the next
> beats work either way. **The safe default for a tight room is to play the
> recording from the start.**

**The result:** a branch and a PR, never a deploy. You have just demonstrated
four Claude Code features working together: **headless mode** (`claude -p` with
an enumerated `--allowedTools` list and no approval surface), a **subagent**
(`incident-responder`, with its own narrower tool list), a **slash command**
(`/triage-incident`, invoked through the `Skill` tool), and a **skill**
(`incident-postmortem`, which is why the write-up is blameless without anyone
asking for that in the prompt).

### 1.4 The pull request (2 min) — **Incidents**

The **Pull request** card appears when the run writes its description: title,
branch, commits, files, and the description with a postmortem draft. Press
**show diff**.

> _One config file, one client change, one test, one runbook edit. Read the
> postmortem: it names the commit and the config value. It does not name the
> author. That instruction lives in `.claude/skills/incident-postmortem/`,
> written once by whoever cares most about how this team does postmortems, and it
> applies to every incident forever._

The nuance worth landing, from the PR description's before/after table:

> _Turning the circuit breaker on and changing nothing else leaves the success
> rate at 70.8% — exactly where it was. It cuts offered load by two thirds by
> stopping our own retries, but it cannot give back the capacity the cache was
> providing. Blast radius and root cause are different problems, and the fix
> addresses both._

Press **Request review** (tagged **SWE**). The card shows the prompt to type and
the timeline gets `review_requested` with a hand-off arrow to **SWE**.

### 1.5 The engineer picks it up (6 min) — **desktop app** **[VARIABLE]**

This is the single most important beat in the demo for a skeptical engineering
audience, and it is the one most often rushed. **Slow down here.**

_Different person, same repository, same rules._ The hook is
`.claude/hooks/protect_secrets.py`, a `PreToolUse` hook that exits 2. Exit 2
denies the call and feeds stderr back to the agent, which then does the compliant
thing — `.env.example` plus `docs/config.md` — **unprompted**, because `CLAUDE.md`
says that is where config changes go.

1. Switch to the Claude Code desktop app and type the prompt from the card:

   > Review the PR on branch incident/INC-4412-&lt;slug&gt;: read .tessera/prs/ for the description, then the diff against main (git diff main...incident/INC-4412-&lt;slug&gt;). Check it against CLAUDE.md's reliability rules and tell me whether the fix is separable from the cleanup.

   Give it two minutes. It should say yes, separable: the TTL restore is the fix;
   the timeout, backoff and breaker are the `CLAUDE.md` reliability rules finally
   being applied. _That is a review conversation, not a rubber stamp._

2. Now walk into the guardrail:

   > The circuit breaker should page risk-platform when it opens. Add PAGERDUTY_RISK_ROUTING_KEY to the .env file so ops can wire it up.

3. The hook exits 2. **Switch to the console Guardrails page**: the feed shows the
   deny with the badge `desktop session`, and the timeline gets
   `guardrail_blocked` on the **SWE** lane. Deliver the line, and pause after it:

   > _That is a hook, not a prompt. It is deterministic code with an exit code,
   > and it just fired from a different person's session on the same repository._

4. Escalate twice, so nobody in the room walks away thinking it was one tool's
   good manners rather than a control:

   > Try adding it with a shell command instead.

   > Read the .env file and tell me what's in it.

   Both denied. Both land in the feed. The shell attempt matters most — the hook
   matches on `Bash` as well as `Edit|Write|MultiEdit|NotebookEdit|Read`, so
   swapping tools is not an escape hatch.

5. Finish the beat cleanly:

   > Commit that on the incident branch with a conventional commit message.

   The PR card's commit count goes up; the timeline gets `pr_updated` on the
   **SWE** lane.

> [!NOTE]
> **If Claude declines to touch `.env` *before attempting* the write** — which
> happens, because it has read `CLAUDE.md` — the hook never fires and you get no
> audit entry. Say: _"make the attempt so the guardrail can log it."_ The hook
> only fires on an attempt, and the attempt is the point.

**The result:** three denials, three audit entries, one compliant change that
nobody asked for explicitly. Features demonstrated: **hooks** (`PreToolUse`, exit
code 2), the **permissions deny list**, **`CLAUDE.md`** (which is why it knew
`.env.example` + `docs/config.md` was the right alternative), and the **audit
trail** at `.tessera/audit.jsonl` that both hooks append to.

### 1.6 Merge and recover (2 min) — **Incidents**

Short, and the payoff for the whole first use case. The argument is about *who
holds the authority*, and it is best made in one sentence over a screen that has
just turned green.

Press **Merge** then **Confirm merge into main** (tagged **SWE**). Switch to
**Overview**: the production tiles go green — success **100%**, p99 **0.54s**,
utilization **0.62** — and the timeline ends with `merged` and `recovered`.

> _Claude proposed. A human disposed. The output of the automation was a pull
> request, never a deploy, and production changed only when someone with the
> authority to change it pressed the button._

**The result:** the loop is closed with a human at the last step. Nothing Claude
Code did in this act could have changed production — that is a property of the
**workflow permissions** and the **tool allowlist**, not of the model's judgement.

---

## Use case 2 — the data scientist and the notebook · ~16 min

### 2.1 The number that stopped a promotion (2 min) — **Models**

Four tiles: champion **0.778**, candidate offline **0.906**, candidate shadow
**0.699**, gap **−0.207**. Below, the shadow AUC by month and the feature stats:
`card_chargeback_rate` is non-zero for **27.4%** of training rows and **14.2%**
of scored rows.

> _Offline this model beat production by thirteen points of AUC. In shadow it is
> worse than production. Every data scientist in this room has had this Tuesday.
> The console has the number; it does not have the explanation._

Press **Run validation gates** (tagged **Data scientist**). Five cards, four of
them **NOT IMPLEMENTED · TESS-2310**.

> _The gates were agreed in a review before anyone implemented them.
> `model-validation.yml` is the contract; the code does not exist yet. Hold that
> thought too._

Press **Open investigation notebook**. JupyterLab opens
`03_v3_shadow_investigation.ipynb`: the three numbers, load cells, three
questions. Run the seed cells (Shift-Enter ×4). Then **save and close the
notebook tab** — Claude is about to edit the file on disk.

### 2.2 Investigate (6 min) — **desktop app** **[VARIABLE]**

> [!WARNING]
> **Before you send the prompt, save and close the notebook tab in JupyterLab.**
> `up.sh` disables JupyterLab autosave for exactly this reason, but an open tab
> will still prompt you. If JupyterLab complains the file changed on disk, choose
> **Revert** — Claude's version is the one you want.

Press **Prompt 1 · investigate** on the Models page and type it:

> Open ml/notebooks/03_v3_shadow_investigation.ipynb. The shadow report in ml/registry/shadow/fraud-v3-candidate.json says fraud-v3-candidate scored 0.906 AUC offline but 0.699 in shadow, below the champion. Investigate in the notebook: reproduce the offline number from notebook 01, then explain the gap with numbers. Add your analysis as new cells and execute the notebook in place with nbconvert so the outputs show in JupyterLab.

It should find that `card_chargeback_rate` in notebook 01 is a `groupby` over the
entire dataset — including each row's own future chargeback — and that disputes
arrive 20–90 days later (median 54). Watch the Guardrails feed tick `NotebookEdit`
and `uv run jupyter nbconvert` allows; the timeline gets `notebook_updated`.

Reopen the notebook in JupyterLab. The table you want:

| feature | AUC |
|---|---|
| baseline, observable features | 0.778 |
| `+ card_chargeback_rate` over all history | **0.906** |
| the same feature, point-in-time | 0.777 |
| the offline model meeting the served feature (= shadow) | 0.699 |

Deliver **both mechanisms, in this order** — leakage first, then train/serve skew
(the full wording is in [2.3 Talking points by seat](#the-data-scientist--does-it-understand-modelling-or-just-pandas)), then:

> _Two things happened. The honest lift of that feature is minus 0.0008 — within
> noise of zero; every point of the improvement was the model reading the answer.
> And the model trained on a feature that looks nothing like the one it meets at
> scoring time, so in shadow it is worse than the champion. This is the single
> most common way a fraud model dies in production, and it usually dies quietly,
> six months later._

**Fallback, fastest first:** on **Models**, pick the golden recording and press
**Play recording** at 8× — it replays this beat and [2.3](#23-productionize-6-min--desktop-app-variable)
together, with the same full-width `RECORDING` banner the triage replay uses, and
leaves the branch, the PR and the executed notebook in place. Say out loud that it
is a recording. If you only need the notebook back,
`./demo/reset-demo.sh --restore-notebook` puts the executed one in place; reopen it.

**The result:** the gap is explained with reproduced numbers, not with a plausible
story. Features demonstrated: the **`NotebookEdit` tool** (Claude edits `.ipynb`
structurally rather than as text), **allowlisted Bash** (`uv run:*` is on the
allow list, which is why nbconvert runs without a prompt), and the
**`model-validator` subagent**'s framing — *start from the assumption that a large
unexplained improvement is a bug*.

### 2.3 Productionize (6 min) — **desktop app** **[VARIABLE]**

The beat that wins the room for a regulated-industry buyer. The finding becomes
code, and that code ships through the same door as the engineer's PR.

Press **Prompt 2 · productionize** and type it:

> Productionize the finding. Add ml/features/aggregates.py with a point-in-time card_chargeback_rate(df, as_of) that only counts chargebacks filed before each transaction, and implement the four gates model-validation.yml already specifies under ml/validation/ with exactly those CLI flags. Keep the notebook's full-data definition as a negative fixture in ml/validation/tests/ so Gate 1 provably fails on it. Add the model card with the model-card skill. Run uv run pytest ml/ before you finish.

While it works, the timeline fills in on its own: `gates_implemented` when
`ml/validation/` appears, `model_card_added` when the card lands.

When it finishes, press **Run validation gates** again: **PASS** ×4, model card
present. Then **Negative proof**: `pytest ml/validation` lists the test that feeds
the notebook's full-history definition to Gate 1 and watches it fail.

> _The gate was written to the contract the team agreed, and the first thing it
> caught was the notebook that started this. The data scientist ships through the
> same door as the engineer and the SRE. That is the part that usually does not
> exist._

**Fallback:** if you already played the recording in
[2.2](#22-investigate-6-min--desktop-app-variable) this beat is already done —
the branch, the gates and the model card came with it. Otherwise
`./demo/reset-demo.sh --restore-gates` recreates the productionized branch from a
recorded run of this prompt (all four gates pass on it); then press
**Run validation gates**.

**The result:** a contract written before the implementation, satisfied by the
implementation, and proven by a test designed to fail. Features demonstrated: a
**skill** (`model-card`, invoked by name in the prompt and producing the MRM
sections the team agreed), **project-scoped conventions** from `CLAUDE.md`, and
the **Actions** workflow as an executable specification.

### 2.4 The contract (2 min)

Show `.github/workflows/model-validation.yml` beside the gate cards: the same four
commands, written before the code.

> _Same rails. Different gates bolted on, not a second stack. Credit scoring
> rides these rails too, with adverse-action reason codes added for ECOA._

---

## Close — 4 min

Four minutes to convert two war stories into a single durable idea. **Do not
introduce anything new here.** Walk the timeline and name the five mechanisms.

**Overview**, scroll to the timeline, or open the timeline on the incident page
full-height. Read the rail top to bottom: SRE → Claude (headless) → SWE (desktop)
→ guardrail → merge → recovered → Data scientist → Claude → gates.

Then **Guardrails**: the counts at the top of the audit feed — how many tool calls
the hooks passed, how many they blocked, **across both sessions**. Point out that
the feed started empty in the Opening.

> _One repository. Three people who share almost no daily context. One set of
> rules that applied to all of them without anyone remembering to apply it — and
> a record of every time it did._

Name the five mechanisms, one line each:

- **`CLAUDE.md`** — it writes like your team
- **hooks** — the things that must never happen, as code with exit codes, with an audit trail
- **skills** — how *this* team does postmortems and model cards
- **subagents** — reviewers with narrow, well-defined scopes
- **Actions** — the same rules at the door, for humans and agents alike

Then, the line that should be the last thing they hear:

> _Every team has these rules. They are usually in someone's head, a wiki page
> nobody reads, and a code review comment written for the fourth time. Here they
> are in the repository, they are executable, and they hold at 3am._

**The result:** the audience leaves with one idea, not seven features. Every
feature you named was something they watched fire, not something you described.

---

## The 25-minute variant

For when you are given half the time you were promised. Keep **1.1**, **1.3 as
the recording at 8×**, **1.5** (the guardrail), **1.6**, and **2.1–2.2**. Skip the
contract walk-through and the productionize beat. Open with two minutes on
Guardrails and close with two.

---

# Part 4 — Under pressure

## 4.1 Recovering mid-demo

| Problem | Do this |
|---|---|
| Live run is slow or wandering | **Cancel**, then **Play recording** at 4× — say it is a recording |
| Live run failed | the failure card's button plays the golden recording |
| Desktop Claude wandered off-script | `Esc` to interrupt, re-prompt more narrowly |
| JupyterLab says the file changed on disk | choose **Revert** — Claude's version is the one you want |
| Either data-scientist beat is running long | **Models** → **Play recording** at 8× — covers 2.2 and 2.3 in one pass; say it is a recording |
| Notebook beat is running long | `./demo/reset-demo.sh --restore-notebook`, reopen the notebook |
| Productionize beat is running long | `Esc`, then `./demo/reset-demo.sh --restore-gates` and **Run validation gates** |
| Console shows `reconnecting…` | it reconnects on its own; a page reload lands on the same state |
| `up.sh` will not stop, or a port is "in use" | `pkill -9 -f "uvicorn services.console"` — a browser tab's open event stream can hold a shutdown |
| Everything is confused | new terminal: `./demo/reset-demo.sh && ./demo/up.sh` |

The captured transcripts in `demo/expected-output/` are text-only fallbacks for
talking through a beat without the UI.

## 4.2 Questions you will get

**"Is that really running, or is it a recording?"** Press **Show the command**.
Live runs show `live` in the run status; recordings show the full-width banner.
Offer to run one live for them after — it costs a few dollars and ten minutes.

**"What stops it deleting the database?"** The Guardrails page: permissions are an
allowlist, the hooks block specific operations deterministically, the headless run
has an enumerated tool allowlist and no approval surface, and the workflow's final
step re-runs both hooks and fails the run if a protected path moved. Point at the
amber `allowlist` rows in the feed — that is a denial happening. Add "and `main`
is protected in Actions" **only** if you enabled branch protection on your remote
([1.6](#branch-protection--only-if-your-plan-allows-it)), so on a private
free-tier repo it is not on.

**"What if it writes a plausible but wrong fix?"** It does sometimes. That is why
the output is a PR and never a deploy, why the command insists on a test that
fails before the fix, and why a human presses **Merge**.

**"Is the incident staged?"** The scenario is constructed — say so — and then show
that the mechanism is not. `git show b745a5a` is a real one-line diff. The metrics
are generated by the capacity model in `services/risk_gateway/simulation.py`, and
the Overview tiles are that model run against the live config:
`uv run python -m services.risk_gateway.simulation`.

Two things are deliberately easier than reality. The deploy record uses the
literal git short SHA, which in most shops it would not. And `metrics.csv` carries
a `cache_hit_rate` series, which points a responder toward the cache faster than a
real dashboard might. Both are demo reliability, not sleight of hand. **Volunteering
them buys you enormous credibility.**

**"Is the shadow number real?"** Yes: `uv run python demo/generate_shadow_report.py`
retrains the candidate exactly as notebook 01 does and scores it on the shadow
window with the feature as served. `demo/verify_leakage.py` prints the
point-in-time comparison.

**"Who is accountable when it is wrong?"** The person who pressed **Merge**. Same
as now.

## 4.3 Failure drills

Rehearse the recoveries *before* you need them. An SE who recovers smoothly from a
wandering run is more credible than one whose demo happened to go perfectly — the
room knows which one is closer to their own experience.

**The meta-talking-point:** when a live run goes sideways in front of an audience,
say so. _"It hit the turn limit"_ or _"it needed two tries"_ is a fine thing to
say. The point is not that it is flawless at 3am; the point is that **when it is
wrong, the worst outcome is a pull request nobody merges.**

1. Practise every row in [4.1](#41-recovering-mid-demo) at least once. Do not read
   them — do them.
2. Rehearse the questions in [4.2](#42-questions-you-will-get) out loud.

**The result:** you can lose a live run and keep the room. That is the difference
between a demo and a presentation.

## 4.4 Certification run

End to end, timed, to a colleague playing the skeptic. No notes for the lines —
this document open for button labels is fine.

Your colleague's job is to interrupt with the questions from
[4.2](#42-questions-you-will-get) at inconvenient moments, and to ask at least one
thing you do not know the answer to. _"I don't know, let me find out"_ is an
acceptable answer in the room, and rehearsing saying it is worth the discomfort
now.

1. Reset and start clean:

   ```bash
   ./demo/reset-demo.sh && ./demo/up.sh
   ```

2. Run [Part 3](#part-3--the-runbook) end to end, timed. Target 50 minutes;
   anything over 60 means you are over-explaining the features and under-showing
   the timeline.

3. Have your colleague score three things, and only these three:

   - Did the **guardrail beat** ([1.5](#15-the-engineer-picks-it-up-6-min--desktop-app-variable))
     land, including both escalations?
   - Did you say **both** mechanisms in [2.2](#22-investigate-6-min--desktop-app-variable),
     in the right order — leakage first, then train/serve skew?
   - When something went wrong or ran long, did you **name it** rather than talk
     over it?

4. Run the [25-minute variant](#the-25-minute-variant) once, on a different day.

**The result:** you can run this demo. The three scored items are the ones that
survive in the audience's memory a week later — the specific tool calls do not.

---

# Part 5 — Reference

## 5.1 Quick reference

```bash
./demo/reset-demo.sh && ./demo/up.sh    # before every run
./demo/reset-demo.sh --check            # readiness only, changes nothing
./demo/reset-demo.sh --restore-notebook # mid-demo fallback, beat 2.2
./demo/reset-demo.sh --restore-gates    # mid-demo fallback, beat 2.3
./demo/reset-demo.sh --adopt-base       # carry demo/ + console changes into demo-base
# ./demo/build_history.sh               # NOT yours to run — see section 1.3
```

| Surface | URL / how |
|---|---|
| Ops console | `http://localhost:8765` |
| JupyterLab | `http://localhost:8888/lab?token=tessera` |
| Desktop app | open on the **repository root**, not a subdirectory |

| Number | Value |
|---|---|
| Auth success, degraded → recovered | 70.8% → 100% |
| p99 latency, degraded → recovered | 8.50s → 0.54s |
| Fraud-model utilization | 7.22× → 0.62 |
| Champion / offline / shadow AUC | 0.778 / 0.906 / 0.699 |
| Honest lift of the leaky feature | −0.0008 AUC |
| Feature non-zero, train vs scored | 27.4% vs 14.2% |
| Chargeback arrival lag | 20–90 days, median 54 |
| Decoy commit / actual cause | `4b56e1d` / `b745a5a` |

## 5.2 What is fictional

Tessera Financial does not exist. Every transaction, applicant, incident, model
and credential in this repository is synthetic. The `.env` file contains
placeholder values that authenticate to nothing; it exists so the secrets
guardrail has a realistic target. The commit authors are fictional too — which
matters in [beat 1.4](#14-the-pull-request-2-min--incidents): `git blame` on the
offending commit names a person, and the `incident-postmortem` skill instructs
Claude to write blamelessly anyway.

## 5.3 Why Claude cannot read `demo/`

`.claude/settings.json` denies `Read` on `demo/**`. This directory is the answer
key — this runbook, the golden recording, the scripts that generate the incident.
Without the deny, an agent triaging INC-4412 can reach it from the README link and
short-circuit the investigation in one file read.

It is also a neat demonstration of the point the guardrail beat makes: scoping an
agent away from files it should not see is a two-line change, enforced by the
harness rather than by asking nicely.

If you want Claude's help editing the demo materials themselves, remove that line
from the deny list first — and **put it back before you present**
(`reset-demo.sh --check` asserts it is there).

> [!WARNING]
> The deny resolves relative to the directory Claude Code was opened on. Opening
> the desktop app or CLI on a **parent** of the repository root loads no project
> settings at all, so neither the deny list nor the hooks are active. Always open
> on the repository root.

## 5.4 Appendix — Claude Design brief for the console theme

Unrelated to presenting; kept here so the demo directory stays one file. Paste the
block below into Claude Design. The variable names are the contract the UI expects
(`web/src/styles/tokens.css`); replace values, never names, and the whole console
restyles without touching a component.

---

Design a light and dark theme for "Tessera Console", an internal payments-platform operations console used live on stage in a 50-minute demo, viewed on a projector at 1080p. Tone: calm, dense, engineering-grade (an SRE dashboard, not a marketing site). Output the result as CSS custom properties with exactly these names, with values for `:root` (light) and `[data-theme="dark"]`:

Surfaces and text: `--color-bg`, `--color-surface`, `--color-surface-2`, `--color-border`, `--color-text`, `--color-text-2`, `--color-text-muted`, `--color-accent`, `--color-accent-contrast`, `--color-focus`.
Status (fixed meaning; an icon and label always accompany them): `--status-good`, `--status-warning`, `--status-serious`, `--status-critical`, `--status-info`, `--status-neutral`.
Personas: `--persona-sre`, `--persona-swe`, `--persona-ds`, `--persona-claude` — four distinct hues usable as chips and as timeline node colours, distinguishable from the status colours.
Chart series, fixed order, never cycled: `--series-1` … `--series-4` (fraud-model rps, cache hit rate, p99 latency, auth success rate — each in its own panel), plus `--chart-grid`, `--chart-axis`, `--chart-marker-deploy`, `--chart-marker-alert`, `--chart-cursor`.
Typography: `--font-sans`, `--font-mono` (a monospace with tabular figures for metrics), `--text-xs`, `--text-sm`, `--text-base`, `--text-lg`, `--text-xl`, `--text-2xl`, `--text-3xl` (hero numbers), `--leading-tight`, `--leading-normal`.
Spacing and shape: `--space-1` … `--space-8` (4 px base), `--radius-sm`, `--radius-md`, `--radius-lg`, `--shadow-1`, `--shadow-2`.

Constraints: all text/surface pairs meet WCAG AA; adjacent chart series stay distinguishable under deuteranopia and protanopia; status colours are never reused as series colours; the dark theme is a selected palette, not an inversion. Also give guidance for these components: metric tile (label, hero value, delta, status pill), status pill, persona chip, agent activity row (tool name, target path in mono, elapsed time, allow/deny badge), PR card (title, branch in mono, commit list, diff stat), incident timeline (vertical rail, persona-coloured nodes, handoff arrows), code/diff block (mono, added/removed line backgrounds), gate card (PASS / BLOCKED / NOT IMPLEMENTED states), and a full-width "RECORDING" banner unmistakable from the back of a room. Return the CSS block first, then the component notes.

---

**Applying the output:**

1. Replace the values in `web/src/styles/tokens.css` (keep both blocks: `:root` and `[data-theme="dark"]`).
2. If it names web fonts, add the `<link>` in `web/index.html`; the fallbacks already cover a machine without them.
3. `npm --prefix web run build` (or just `./demo/up.sh`, which rebuilds when sources change).
