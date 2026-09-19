# Sales engineering enablement — running the Tessera demo

**Total: ~3h 45m.** Tasks 1–5 are once per laptop. Tasks 6–12 are the demo
itself, rehearsed beat by beat. Tasks 13–14 are what separates someone who has
seen the demo from someone who can run it in front of a hostile room.

You are not learning a product tour. You are learning to run a fifty-minute
argument that three different skeptics can each verify from their own seat.

---

## Module 0 — What you are actually demonstrating

**The claim.** Three people who share almost no daily context work in one
repository, under one set of rules that are *executable* — and those rules hold
whether a human is watching or not.

**The scenario, in one paragraph.** Tessera Financial is a fictional card
issuer (PCI-DSS Level 1, SOC 2 Type II) where every card authorization blocks on
one synchronous fraud-model call at ~400 requests a second, and that call fails
closed — no decision means a decline. The demo runs two failures of that same
dependency. **INC-4412** is the loud one: a deploy labelled a memory
optimisation set the risk gateway's cache TTL to zero, the cache had been
absorbing ~77% of scoring calls, and the resulting 2.7× overload plus retry
amplification dropped authorization success from 99.9% to 71% — roughly 41,300
good authorizations declined across 2,184 merchants. **TESS-2310** is the quiet
one: a fraud model that scored 0.906 AUC offline scored 0.699 in shadow, below
the 0.778 champion, because its strongest feature was computed with a `groupby`
over the whole table and so handed every row its own chargeback — a label that
arrives 20 to 90 days after the transaction it describes. One pages someone at
3am; the other would have shipped and died silently six months later.

**Who is in the room and what they doubt.**

| Seat | The question they are actually asking | The beat that answers it |
|---|---|---|
| **SRE** | "What does it do at 3am, and what stops it doing harm?" | Task 7 — headless triage with an enumerated tool allowlist |
| **SWE** | "Will it respect our rules, or just my prompt?" | Task 8 — the hook fires and cannot be talked out of it |
| **Data scientist** | "Does it understand modelling, or just pandas?" | Tasks 10–11 — leakage found with numbers, then shipped through gates |

**The three surfaces you will use, and why each one is there.**

- **Claude Code CLI, headless (`claude -p`)** — the 3am story. No human, no
  approval prompt, an enumerated allowlist. This is the one SREs care about.
- **Claude Code desktop app** — the working session. Same repository, same
  `.claude/` rules, different person. This is where the guardrail collision
  lands and where the notebook work happens.
- **GitHub Actions** — the same rules at the door. Proves the guardrails are not
  a local-machine courtesy.

---

# Task 1. Environment setup
(Duration 00h:25m)

## Overview

You are installing the toolchain and building the ops console front end. Most of
this is download time, not your time.

Nothing in the demo depends on Docker, a database, or any network call other
than Claude itself. Say this out loud when you present — **a demo that depends
on someone else's uptime is a demo that fails in front of an audience**, and an
SRE in the room will respect that you made that choice deliberately.

**Talking points you are earning here (for later, not now):**

- The whole thing is one repository. There is no second stack, no sidecar
  service, no "and then you'd integrate it with…". The agent reads the repo the
  same way your engineers do.
- `CLAUDE.md` at the repo root is the file that makes Claude write like your
  team. Open it during setup and read it — you will reference it in Task 8.

> [!WARNING]
> **Steps 3 and 4 take 10–20 minutes of download and build time.** Do not sit
> and watch them. Start them, then read Module 0 and skim `CLAUDE.md` and
> `demo/DEMO_RUNBOOK.md` in a second terminal session while they run. Come back
> when the prompt returns.
>
> To open a second session in a terminal:
> ```bash
> # macOS Terminal or iTerm: Cmd-T for a new tab, then
> cd ~/path/to/tessera-platform && claude
> ```
> In the Claude Code desktop app, use the **+** button (or Cmd-N) to open a
> second session on the same folder. Both sessions share the same `.claude/`
> rules — which is itself the point you make in Task 8.

## Steps

1. Confirm the prerequisites. Each of these must return cleanly:

   ```bash
   claude -p "reply with the word OK" && uv --version && node --version && git --version
   ```

   `claude -p` must print `OK`. Note that `claude --version` succeeds even when
   you are logged out, so it is not a valid check — this one is.

2. Clone your team's copy of the demo repository — the one carrying the
   `demo-base` tag — and enter it:

   ```bash
   git clone https://github.com/<your-org>/tessera-platform.git
   cd tessera-platform
   ```

   A normal clone brings the tags down with it, which is all the setup the git
   side needs. **Never run `git init`, and never delete `.git`**: the commit
   history is the evidence the whole SRE beat is built on. Task 2 checks it.

3. Install Python dependencies, including the notebooks group JupyterLab lives
   in:

   ```bash
   uv sync --all-groups
   ```

4. Build the ops console front end:

   ```bash
   npm --prefix web ci && npm --prefix web run build
   ```

5. Open `CLAUDE.md` and read the four rule blocks — money, security,
   reliability, conventions. **The result:** you now know where the rules the
   demo enforces actually live. This is the `CLAUDE.md` feature of Claude Code:
   project memory that is loaded into every session automatically, for every
   person, without anyone remembering to paste it into a prompt.

---

# Task 2. Verify the demo history
(Duration 00h:05m)

## Overview

The incident in Task 7 is solved by correlating a deploy record against `git
log`. The commit history *is* the evidence, so before anything else, confirm it
arrived intact.

**You are not building anything here.** The synthetic history and the
`demo-base` tag were authored once, by whoever set up your team's repository,
and they came down with your clone. This task is three commands that all read.

> [!WARNING]
> **Never run `./demo/build_history.sh`.** It is the authoring step for the
> person who originally created the demo, and it begins by deleting `.git` —
> which on your clone destroys the `origin` you just cloned from, the
> `demo-base` tag, and your reflog. The script refuses to run without `--force`
> for exactly this reason, and nothing in your setup ever needs it.
>
> `reset-demo.sh` is the reset. `build_history.sh` is not a reset, and it is
> not yours to run.

**Talking points you are earning here:**

- The deploy record for the 14:02 deploy names revision `88c2501`, which is a
  one-line docstring change. The actual cause is `8067a38`, which that deploy
  also carried. **This trap is the whole reason the triage beat is impressive** —
  a naive responder reads the deploy record, reads the diff, finds nothing, and
  stalls. Claude widens to `git log -- services/risk_gateway/` and finds the
  other three commits that deploy shipped.
- When someone asks "is the incident staged?", the honest answer is: the
  *scenario* is constructed, the *mechanism* is not. `git show 8067a38` is a
  real one-line diff and the metrics are generated by an actual capacity model.

## Steps

1. Confirm the anchor tag came down with the clone. It is what every reset
   rewinds to, so nothing works without it:

   ```bash
   git tag --list demo-base
   ```

   You want one line back: `demo-base`. If it is empty, the repository you
   cloned has not pushed its tag — ask whoever maintains it to run
   `git push origin demo-base`. Do **not** reach for `build_history.sh`.

2. Confirm the trap is armed:

   ```bash
   git show --stat 88c2501 && git show 8067a38
   ```

3. Confirm you are starting from the anchor:

   ```bash
   git log --oneline -1 demo-base && git status --short
   ```

   **The result:** `88c2501` is a one-line docstring change — the revision the
   deploy record names — and `8067a38` is the one-line TTL change that actually
   caused the incident. Both present, a clean tree, and `demo-base` resolving
   means every later task will work. You did all of this with reads; the demo's
   evidence is something you inspect, never something you generate.

---

# Task 3. Point the Actions beats at a repo you own (optional, recommended)
(Duration 00h:15m)

## Overview

Everything else in the demo runs locally. This task converts two beats — the
automated PR review and the alert-triggered triage — from "here is the workflow
file" into "here is a runner executing it."

Your clone's `origin` is your team's shared copy. You do not want to open demo
pull requests against it, every SE would collide on the same branch names, and
the Actions runs need an API key scoped to you — so the first thing this task
does is move the shared copy aside and give you a remote of your own.

You can skip this entire task and the demo still works. But being able to say
*"the same command runs in Actions, here it is running"* is worth fifteen
minutes.

**Talking points you are earning here:**

- `.github/workflows/claude-incident-fix.yml` is genuinely interesting to read
  aloud. The permissions block grants `contents: write` — enough to push a
  branch — and nothing that would let the job deploy. Read the last step too:
  it runs `if: always()`, re-runs both hook selftests, and fails the run if
  `.env` or `.claude/hooks/` moved. *The guardrails are not optional just
  because no one is watching.*
- `claude-code-review.yml` runs the `payments-reviewer` subagent against every
  PR diff. That is the same subagent definition in `.claude/agents/` that a
  developer invokes locally — one definition, two surfaces.

> [!WARNING]
> **Branch protection needs GitHub Pro or a public repository.** Step 1 creates
> a *private* repo, so on a free-tier account step 4 of
> `demo/PUSH_AND_VERIFY.md` returns **403 — "Upgrade to GitHub Pro or make this
> repository public."** Both the protection API and the rulesets API refuse.
>
> **Never say "`main` is protected in Actions" without checking.** It is the one
> containment claim in this demo that depends on your GitHub settings rather
> than on anything in the repository, and it is the one a skeptical SRE is most
> likely to ask to see. Check before you present:
>
```bash
gh api repos/{owner}/{repo}/branches/main/protection >/dev/null 2>&1 \
  && echo "protected — you may say so" \
  || echo "NOT protected — do not claim it"
```
> Everything else in the containment story holds either way, and the presenter
> docs now lead with those: the enumerated tool allowlist, the hooks on every
> write, no deployment permission in the job, and a final workflow step that
> fails the run if a protected path moved. Those are properties of the
> repository, which makes them the stronger argument anyway.

## Steps

1. Keep the team copy as `upstream`, then create a remote you own. Prefer a
   personal account or scratch org — the repo contains a realistic-looking
   (synthetic) `.env`:

   ```bash
   git remote rename origin upstream
   gh repo create tessera-platform-demo --private --source=. --remote=origin --push
   ```

2. Push the anchor tag to your own remote too. `gh repo create --push` sends
   branches, not tags, and without this a fresh clone of *your* copy cannot
   reset:

   ```bash
   git push origin demo-base
   ```

3. Add the API key that pays for the Actions runs. Scope it to this repository:

   ```bash
   gh secret set ANTHROPIC_API_KEY
   ```

4. Install the GitHub app so `@claude` mentions and the review workflow can act
   on PRs. Run `claude`, then `/install-github-app`.

5. Decide on branch protection using the warning above, then run the check in
   it so you know which state you are in. If it succeeded, verify in
   Settings → Branches that direct pushes to `main` are blocked. If it 403'd,
   simply drop that one claim — the rest of the containment story is unchanged.

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

7. Clean up:

   ```bash
   git checkout main && git branch -D demo/verify-review
   git push origin --delete demo/verify-review
   ```

   **The result:** you have proven the guardrails run in CI, not just locally.
   This was done using **Claude Code GitHub Actions** (`claude-code-action`)
   plus the **subagent** and **hook** definitions checked into the repo —
   the identical `.claude/hooks/pii_scan.py` that runs in an interactive session
   runs as a CI step in `ci.yml`.

---

# Task 4. Record the fallbacks
(Duration 00h:45m)

## Overview

Three beats in the demo are live Claude runs. Live runs are the point — and
live runs sometimes wander. This task records a known-good version of each one
so that when a run goes long in front of an audience, you press a button
instead of apologising.

**You will use these. Plan on it.** The runbook's own advice is that *the safe
default for a tight room is to play the recording from the start.*

**Talking points you are earning here:**

- When you play a recording, **say so, out loud, every time**. The console shows
  a full-width `RECORDING` banner in a colour nobody can miss. The line is:
  *"This is a recording of the same run from earlier today, played at four times
  speed. Everything you see it do, it did."* Presenting a recording as a live
  run is the kind of thing that gets noticed, and it costs you the room.
- Playing the golden recording restores the branch and the PR at the end, so
  every beat after it still works. You are never stranded.

> [!WARNING]
> **Step 2 is a real headless Claude run: 8–12 minutes and a few dollars of API
> spend. Steps 4 and 5 are 6–10 minutes each.** Total unattended time is around
> 35 minutes.
>
> Start step 2, then leave this task and go read Tasks 6 through 12 in a second
> session. Come back when the script prints its summary.
>
> ```bash
> # new terminal tab (Cmd-T), same repo:
> cd ~/path/to/tessera-platform && claude
> ```
> Then ask that second session something useful while you wait, for example:
> `explain what services/risk_gateway/simulation.py computes and which numbers
> on the console Overview page come from it`. Note that `reset-demo.sh` refuses
> to run while a headless run is active — so do not try to reset from the second
> session until step 2 finishes.

## Steps

1. Start the demo services and leave them running:

   ```bash
   ./demo/up.sh
   ```

   This starts the ops console on `http://localhost:8765` and JupyterLab on
   `http://localhost:8888/lab?token=tessera`. `Ctrl-C` stops both.

2. In a second terminal, on a clean `main`, record the golden triage run:

   ```bash
   ./demo/record-golden-run.sh
   ```

   It runs one real headless triage and copies the stream, the PR description
   and the branch patch into `demo/recordings/triage-INC-4412/`.

3. Open the ops console at `http://localhost:8765`, go to **Incidents** and
   press **Play recording** at **4×** to confirm the playback works and restores
   the PR.

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

6. **The result:** `./demo/reset-demo.sh --check` now reports
   `golden triage recording present`, `executed notebook fallback present` and
   `productionized-branch fallback present`. You were using **Claude Code
   headless mode** (`claude -p`) for the recording, and the **desktop app** for
   the two interactive beats — the same repository and the same `.claude/`
   rules in both.

---

# Task 5. The pre-flight and the reset ritual
(Duration 00h:05m)

## Overview

This is the two-command ritual you run before every single demo, forever. Learn
it now so it is muscle memory rather than something you look up while an
audience watches.

`reset-demo.sh` backs up uncommitted work to a timestamped patch outside the
repository (it deliberately does **not** use `git stash`), hard-resets `main` to
the `demo-base` tag, deletes every other branch, clears the console's runtime
state under `.tessera/`, regenerates the synthetic data, notebooks, incident
evidence and model registry, re-syncs the commit SHAs quoted in the presenter
docs, and re-runs the readiness checks.

**Talking points you are earning here:** none — this is stagecraft. But knowing
that the reset regenerates the evidence bundle from a generator is what lets you
answer *"is the incident staged?"* honestly and immediately.

> [!WARNING]
> **`reset-demo.sh` is the only reset.** If a run leaves the repository in a
> state this does not fix, the answer is still this command — never
> `build_history.sh`, which deletes `.git` and would cost you the `origin` you
> created in Task 3, the `ANTHROPIC_API_KEY` link that comes with it, the
> `demo-base` tag and your reflog. See the warning in Task 2.

## Steps

1. Run the readiness check on its own. It changes nothing:

   ```bash
   ./demo/reset-demo.sh --check
   ```

2. Read the output. You want all `ok` and the final line `Ready.` The checks
   worth understanding, because they are the demo's preconditions:

   - `deploy record names 88c2501, which is NOT the cause` — the trap is armed
   - `the causing commit 8067a38 appears nowhere in the evidence bundle`
   - `demo/ is read-denied to the agent` — the answer key stays closed
   - `investigation notebook (03) is the 5-cell seed` — Claude has work to do
   - `ml/validation/ absent` — the gates read NOT IMPLEMENTED until Task 11

3. Now practise the real ritual:

   ```bash
   ./demo/reset-demo.sh && ./demo/up.sh
   ```

4. **The result:** console on `:8765`, JupyterLab on `:8888`, and a repository in
   its starting state. Note what the deny check protects: `.claude/settings.json`
   contains `"Read(./demo/**)"` in its **deny list**, so the agent cannot read
   the runbook, the recordings or the generators — this is Claude Code's
   **permissions** system, and it is also the cleanest possible preview of the
   argument you make in Task 8.

---

# Task 6. Rehearse the opening
(Duration 00h:04m)

## Overview

Four minutes to establish the stakes and plant the guardrails, so that when a
hook fires in Task 8 the audience already knows what they are looking at.

**Screen layout.** Left half of the projector: the console in a browser. Right
half: the Claude Code desktop app, opened on the **repository root** — the
guardrails resolve relative to it, and starting in a subdirectory means no
guardrails at all, which removes the spine of the whole first use case.

**The lines to land:**

> *Tessera issues cards and moves money. PCI Level 1, SOC 2. About four hundred
> authorizations a second. Right now the authorization path is degraded, and
> everything on this screen is computed from what `main` would actually run —
> not from a mock.*

> *A hook is a program with an exit code. It cannot be talked out of it, and it
> runs the same at 2pm with an audience and at 3am with nobody awake. The audit
> trail underneath is every decision those hooks made. Right now it is empty. It
> will not stay empty.*

## Steps

1. Open the console **Overview** page. The production tiles are red: auth
   success **70.8%**, p99 **8.50s**, fraud-model utilization **7.22×**, cache
   hit **0%**.

2. Deliver the first line above. Do not explain the incident yet.

3. Click **Guardrails**. Point at the three columns without dwelling on any of
   them: the **deny list** (the agent cannot even *read* `.env`, key material or
   `demo/`), the **hooks** (two programs with exit codes — one before every
   write, one after), and **the same checks at the door** (the identical scripts
   run in GitHub Actions).

4. Deliver the second line, and land on *"right now it is empty."*

5. **The result:** the audience has been shown an empty audit feed and told it
   will fill. Everything after this is that promise being kept. You have
   previewed three Claude Code features at once — **permissions**, **hooks**,
   and the **Actions** symmetry — without explaining any of them.

---

# Task 7. Rehearse Act 1 — the SRE and the headless triage
(Duration 00h:11m)

## Overview

The centrepiece for the SRE seat. You press one button and narrate while a
headless Claude run reads evidence, correlates it against git history, proves
its hypothesis by reproducing the failure, writes a fix, writes a regression
test, and opens a PR.

**What makes this land is that you are not driving.** There is no human in the
loop, no approval dialog, and no way to steer it mid-run. That is the 3am story.

**Talking points, in the order the feed will give them to you:**

| Phase | What to say |
|---|---|
| **Evidence** — `Read ops/incidents/INC-4412/…` | *It reads all five files before forming a hypothesis. That is in the command, not in the model.* |
| **Correlate** — `git show 88c2501` | *The deploy record named a docstring change. One line, no behaviour. This is the trap: a deploy ships whatever is at HEAD, and HEAD is not the cause.* |
| `git log … -- services/risk_gateway/` | *It widens to the whole set of commits that deploy carried. Three touched the gateway that day.* |
| **Prove** — `uv run python -m services.risk_gateway.simulation` | *It reproduces the incident from the shipped config: utilization 7.22, success 70.8% — the numbers in the alert. The model is reproducing the real failure, not a plausible one.* |
| **Fix** — `Edit services/risk_gateway/config.py` | *Cache TTL back to 300, a timeout on the call, backoff with jitter. The trigger was one line; what made it an incident was the call policy.* |
| **Test** — `Write …/tests/test_…py` then `uv run pytest` | *A regression test — and it checks the test fails without the fix. That is the difference between a fix and a claim.* |
| **PR** — `git checkout -b incident/INC-4412-…` | *Branch, commit, description. Never a deploy.* |

Two rows deserve a sentence the moment they appear:

- an amber **allowlist** row — *That tool was not on the allowlist, so it was
  denied automatically. Nobody is there to approve it. It adapted.*
- the footer count of **hook checks passed** — *Every one of those was the
  secrets guardrail running on a real tool call, headless.*

> [!WARNING]
> **A live run takes 8–12 minutes and 30–45 turns. This is the longest
> unattended stretch in the demo, and it is where you do your talking.** Do not
> stand in silence watching a feed scroll.
>
> Open **Guardrails** in a second browser tab while it runs — the audit feed
> shows the same checks with the badge `headless run`, which is a second thing
> to point at when the main feed is quiet.
>
> **If it has not reached the PR phase by the eight-minute mark**, press
> **Cancel**, then **Play recording** at **4×** (about two minutes) and say
> plainly that it is a recording.

## Steps

1. On **Overview**, press **Replay 13:30 → 14:40**. The charts replay the
   incident-day telemetry at ten minutes a second. Narrate: *watch the second
   panel — the cache hit rate falls off a cliff at 14:03, one minute after a
   deploy, and load on the fraud model goes up twelve times while authorization
   volume does not move.*

2. At **14:11** the Alerting card turns critical and the timeline gets its first
   node, `alert_fired`, tagged **SRE**. Press **Open INC-4412 →**.

3. On **Incidents**, click through the **Evidence bundle** tabs, **deploys**
   first. Land the trap: *the deploy on the risk gateway went out at 14:02 and
   the deploy record names revision `88c2501`. Hold that thought.*

4. Press **Show the command**. This puts the actual argv on screen. Say: *the
   prompt, the tool allowlist and the turn budget are read from
   `claude-incident-fix.yml` at run time — the same file the PagerDuty webhook
   triggers. The console cannot drift from the automation it stands in for.*

5. Press **Triage with Claude**. Narrate the phases from the table above as they
   arrive. Say the allowlist line and the hook-count line when those rows appear.

6. When the **Pull request** card appears, press **show diff**: one config file,
   one client change, one test, one runbook edit. Then read the postmortem
   aloud and land it: *it names the commit and the config value. It does not
   name the author. That instruction lives in
   `.claude/skills/incident-postmortem/`, written once by whoever cares most
   about how this team does postmortems, and it applies to every incident
   forever.*

7. Land the nuance from the PR's before/after table: *turning the circuit
   breaker on and changing nothing else leaves the success rate at 70.8% —
   exactly where it was. It cuts offered load by two thirds by stopping our own
   retries, but it cannot give back the capacity the cache was providing. Blast
   radius and root cause are different problems, and the fix addresses both.*

8. **The result:** a branch and a PR, never a deploy. You have just demonstrated
   four Claude Code features working together: **headless mode** (`claude -p`
   with an enumerated `--allowedTools` list and no approval surface), a
   **subagent** (`incident-responder`, with its own narrower tool list), a
   **slash command** (`/triage-incident`, invoked through the `Skill` tool), and
   a **skill** (`incident-postmortem`, which is why the write-up is blameless
   without anyone asking for that in the prompt).

---

# Task 8. Rehearse Act 1 — the engineer and the guardrail
(Duration 00h:06m)

## Overview

This is the single most important beat in the demo for a skeptical engineering
audience, and it is the one most often rushed. Slow down here.

The setup: a *different person* picks up the PR in a *different session*, and
the first thing they hit is a hook. The hook is `.claude/hooks/protect_secrets.py`,
a `PreToolUse` hook that exits 2. Exit 2 denies the call and feeds stderr back
to the agent, which then does the compliant thing — `.env.example` plus
`docs/config.md` — **unprompted**, because `CLAUDE.md` says that is where config
changes go.

**The line, and it is worth pausing after:**

> *That is a hook, not a prompt. It is deterministic code with an exit code, and
> it just fired from a different person's session on the same repository.*

Then the two escalations, so nobody in the room walks away thinking it was one
tool's good manners rather than a control.

> [!NOTE]
> **If Claude declines to touch `.env` *before attempting* the write** — which
> happens, because it has read `CLAUDE.md` — the hook never fires and you get no
> audit entry. Say: *"make the attempt so the guardrail can log it."* The hook
> only fires on an attempt, and the attempt is the point.

## Steps

1. Press **Request review** in the console (tagged **SWE**). The timeline gets
   `review_requested` with a hand-off arrow to the **SWE** lane, and the card
   shows the prompt to type.

2. Switch to the Claude Code desktop app and type the prompt from the card:

   > Review the PR on branch incident/INC-4412-&lt;slug&gt;: read .tessera/prs/ for the description, then the diff against main (git diff main...incident/INC-4412-&lt;slug&gt;). Check it against CLAUDE.md's reliability rules and tell me whether the fix is separable from the cleanup.

   Give it two minutes. It should say yes, separable: the TTL restore is the
   fix; the timeout, backoff and breaker are the `CLAUDE.md` reliability rules
   finally being applied. *That is a review conversation, not a rubber stamp.*

3. Now walk into the guardrail:

   > The circuit breaker should page risk-platform when it opens. Add PAGERDUTY_RISK_ROUTING_KEY to the .env file so ops can wire it up.

4. The hook exits 2. **Switch to the console Guardrails page**: the feed shows
   the deny with the badge `desktop session`, and the timeline gets
   `guardrail_blocked` on the **SWE** lane. Deliver the line above. Pause.

5. Escalate twice, so it is clearly a control and not a tool's preference:

   > Try adding it with a shell command instead.

   > Read the .env file and tell me what's in it.

   Both denied. Both land in the feed. The shell attempt matters most — the hook
   matches on `Bash` as well as `Edit|Write|MultiEdit|NotebookEdit|Read`, so
   swapping tools is not an escape hatch.

6. Finish the beat cleanly:

   > Commit that on the incident branch with a conventional commit message.

   The PR card's commit count goes up; the timeline gets `pr_updated`.

7. **The result:** three denials, three audit entries, one compliant change that
   nobody asked for explicitly. Features demonstrated: **hooks** (`PreToolUse`,
   exit code 2), the **permissions deny list**, **`CLAUDE.md`** (which is why it
   knew `.env.example` + `docs/config.md` was the right alternative), and the
   **audit trail** at `.tessera/audit.jsonl` that both hooks append to.

---

# Task 9. Rehearse Act 1 — merge and recover
(Duration 00h:02m)

## Overview

Short, and the payoff for the whole first use case. The argument is about *who
holds the authority*, and it is best made in one sentence over a screen that has
just turned green.

> *Claude proposed. A human disposed. The output of the automation was a pull
> request, never a deploy, and production changed only when someone with the
> authority to change it pressed the button.*

This is also the honest answer to *"what if it writes a plausible but wrong
fix?"* — it does, sometimes. That is why the output is a PR, why the command
insists on a test that fails before the fix, and why a human presses **Merge**.

## Steps

1. Press **Merge**, then **Confirm merge into main** (tagged **SWE**).

2. Switch to **Overview**. The production tiles go green: success **100%**, p99
   **0.54s**, utilization **0.62**. The timeline ends with `merged` and
   `recovered`.

3. Deliver the line above.

4. **The result:** the loop is closed with a human at the last step. Nothing
   Claude Code did in this act could have changed production — that is a
   property of the **workflow permissions** and the **tool allowlist**, not of
   the model's judgement.

---

# Task 10. Rehearse Act 2 — the data scientist finds the leak
(Duration 00h:08m)

## Overview

A different skeptic, a different failure mode. The number that stopped a
promotion: offline **0.906**, shadow **0.699**, champion **0.778**, gap
**−0.207**.

> *Offline this model beat production by thirteen points of AUC. In shadow it is
> worse than production. Every data scientist in this room has had this Tuesday.
> The console has the number; it does not have the explanation.*

**There are two mechanisms and you must say both, in this order:**

1. **Leakage.** `card_chargeback_rate` was computed with a `groupby` over all
   history, including each row's own future chargeback. Disputes arrive 20–90
   days later (median 54). The point-in-time version of the feature is worth
   **−0.0008 AUC** — say *"within noise of zero"*, not *"exactly zero"*, because
   the number on screen is negative.
2. **Train/serve skew.** The offline model learned a feature that is non-zero
   **27.4%** of the time in training; at scoring it is non-zero **14.2%** of the
   time. The same model meeting the served feature scores **0.699** — below the
   champion. That is what shadow measured.

**The closing line for this beat:** *This is not an exotic mistake. It is the
single most common way a fraud model dies in production, and it dies quietly,
six months later, when someone finally compares backtest to booked performance.*

> [!WARNING]
> **Before you send the prompt, save and close the notebook tab in JupyterLab.**
> Claude is about to edit that file on disk. `up.sh` disables JupyterLab
> autosave for exactly this reason, but an open tab will still prompt you.
>
> If JupyterLab complains the file changed on disk, choose **Revert** —
> Claude's version is the one you want.
>
> **If the beat runs long:** `./demo/reset-demo.sh --restore-notebook` puts the
> executed fallback in place; reopen the notebook and carry on.

## Steps

1. Go to the console **Models** page. Four tiles and, below them, the shadow AUC
   by month and the feature stats. Deliver the opening line above.

2. Press **Run validation gates**. Five cards appear, four of them
   **NOT IMPLEMENTED · TESS-2310**. Say: *the gates were agreed in a review
   before anyone implemented them. `model-validation.yml` is the contract; the
   code does not exist yet. Hold that thought too.*

3. Press **Open investigation notebook**. JupyterLab opens
   `03_v3_shadow_investigation.ipynb` — three numbers, load cells, three
   questions. Run the seed cells (Shift-Enter ×4), then **save and close the
   tab**.

4. Press **Prompt 1 · investigate** on the Models page and type it into the
   desktop app:

   > Open ml/notebooks/03_v3_shadow_investigation.ipynb. The shadow report in ml/registry/shadow/fraud-v3-candidate.json says fraud-v3-candidate scored 0.906 AUC offline but 0.699 in shadow, below the champion. Investigate in the notebook: reproduce the offline number from notebook 01, then explain the gap with numbers. Add your analysis as new cells and execute the notebook in place with nbconvert so the outputs show in JupyterLab.

5. While it works, watch the **Guardrails** feed tick `NotebookEdit` and
   `uv run jupyter nbconvert` allows; the timeline gets `notebook_updated`.

6. Reopen the notebook in JupyterLab. The table you want:

   | feature | AUC |
   |---|---|
   | baseline, observable features | 0.778 |
   | `+ card_chargeback_rate` over all history | **0.906** |
   | the same feature, point-in-time | 0.777 |
   | the offline model meeting the served feature (= shadow) | 0.699 |

7. Deliver both mechanisms and the closing line.

8. **The result:** the gap is explained with reproduced numbers, not with a
   plausible story. Features demonstrated: the **`NotebookEdit` tool** (Claude
   edits `.ipynb` structurally rather than as text), **allowlisted Bash**
   (`uv run:*` is on the allow list, which is why nbconvert runs without a
   prompt), and the **`model-validator` subagent**'s framing — *start from the
   assumption that a large unexplained improvement is a bug*.

---

# Task 11. Rehearse Act 2 — productionize through the gates
(Duration 00h:06m)

## Overview

The beat that wins the room for a regulated-industry buyer. The finding becomes
code, and that code ships through the same door as the engineer's PR.

> *The gate was written to the contract the team agreed, and the first thing it
> caught was the notebook that started this. The data scientist ships through
> the same door as the engineer and the SRE. That is the part that usually does
> not exist.*

**What "productionize" means here, concretely:** point-in-time aggregates with
an `as_of` cutoff, the four gates from `model-validation.yml` with their exact
CLI flags, a negative fixture that proves Gate 1 catches the notebook's original
definition, and a model card for MRM review.

**Breadth, in one sentence, when someone asks about credit:** *Credit scoring
and customer profiling ride the same rails; credit adds adverse-action reason
codes for ECOA/FCRA. Different gates bolted on, not a second stack.*

> [!WARNING]
> **If this runs long, press `Esc`, then run `./demo/reset-demo.sh
> --restore-gates`** and press **Run validation gates**. That recreates the
> productionized branch from a recorded run of this exact prompt, and all four
> gates pass on it.

## Steps

1. Press **Prompt 2 · productionize** and type it into the desktop app:

   > Productionize the finding. Add ml/features/aggregates.py with a point-in-time card_chargeback_rate(df, as_of) that only counts chargebacks filed before each transaction, and implement the four gates model-validation.yml already specifies under ml/validation/ with exactly those CLI flags. Keep the notebook's full-data definition as a negative fixture in ml/validation/tests/ so Gate 1 provably fails on it. Add the model card with the model-card skill. Run uv run pytest ml/ before you finish.

2. While it works, the timeline fills in on its own: `gates_implemented` when
   `ml/validation/` appears, `model_card_added` when the card lands.

3. When it finishes, press **Run validation gates** again: **PASS** ×4, model
   card present.

4. Press **Negative proof**. `pytest ml/validation` lists the test that feeds
   the notebook's full-history definition to Gate 1 and watches it fail.

5. Show `.github/workflows/model-validation.yml` beside the gate cards — the
   same four commands, written before the code. Say: *same rails, different
   gates bolted on, not a second stack.*

6. **The result:** a contract written before the implementation, satisfied by
   the implementation, and proven by a test designed to fail. Features
   demonstrated: a **skill** (`model-card`, invoked by name in the prompt and
   producing the MRM sections the team agreed), **project-scoped conventions**
   from `CLAUDE.md`, and the **Actions** workflow as an executable specification.

---

# Task 12. Rehearse the close
(Duration 00h:04m)

## Overview

Four minutes to convert two war stories into a single durable idea. Do not
introduce anything new here. Walk the timeline and name the five mechanisms.

> *One repository. Three people who share almost no daily context. One set of
> rules that applied to all of them without anyone remembering to apply it — and
> a record of every time it did.*

Then, the line that should be the last thing they hear:

> *Every team has these rules. They are usually in someone's head, a wiki page
> nobody reads, and a code review comment written for the fourth time. Here they
> are in the repository, they are executable, and they hold at 3am.*

## Steps

1. Go to **Overview** and scroll to the timeline (or open the incident page
   timeline full-height). Read the rail top to bottom: SRE → Claude (headless) →
   SWE (desktop) → guardrail → merge → recovered → Data scientist → Claude →
   gates.

2. Switch to **Guardrails** and read the counts at the top of the audit feed:
   how many tool calls the hooks passed, how many they blocked, **across both
   sessions**. Point out that the feed started empty in Task 6.

3. Name the five mechanisms, one line each:

   - **`CLAUDE.md`** — it writes like your team
   - **hooks** — the things that must never happen, as code with exit codes, with an audit trail
   - **skills** — how *this* team does postmortems and model cards
   - **subagents** — reviewers with narrow, well-defined scopes
   - **Actions** — the same rules at the door, for humans and agents alike

4. Deliver the closing line.

5. **The result:** the audience leaves with one idea, not seven features. Every
   feature you named was something they watched fire, not something you
   described.

---

# Task 13. Failure drills
(Duration 00h:15m)

## Overview

Rehearse the recoveries *before* you need them. An SE who recovers smoothly from
a wandering run is more credible than one whose demo happened to go perfectly —
the room knows which one is closer to their own experience.

**The meta-talking-point:** when a live run goes sideways in front of an
audience, say so. *"It hit the turn limit"* or *"it needed two tries"* is a fine
thing to say. The point is not that it is flawless at 3am; the point is that
**when it is wrong, the worst outcome is a pull request nobody merges.**

## Steps

1. Practise each of these at least once. Do not read them — do them:

   | Problem | Do this |
   |---|---|
   | Live run is slow or wandering | **Cancel**, then **Play recording** at 4× — say it is a recording |
   | Live run failed | the failure card's button plays the golden recording |
   | Desktop Claude wandered off-script | `Esc` to interrupt, re-prompt more narrowly |
   | JupyterLab says the file changed on disk | choose **Revert** — Claude's version is the one you want |
   | Notebook beat running long | `./demo/reset-demo.sh --restore-notebook`, reopen |
   | Productionize beat running long | `Esc`, then `./demo/reset-demo.sh --restore-gates` |
   | Console shows `reconnecting…` | it reconnects on its own; a reload lands on the same state |
   | `up.sh` will not stop, or a port is "in use" | `pkill -9 -f "uvicorn services.console"` |
   | Everything is confused | new terminal: `./demo/reset-demo.sh && ./demo/up.sh` |

2. Rehearse the four questions you will definitely be asked, out loud:


   - **"Is that really running, or is it a recording?"** Press **Show the
     command**. Live runs show `live` in the run status; recordings show the
     full-width banner. Offer to run one live for them afterwards — it costs a
     few dollars and ten minutes.
   - **"What stops it deleting the database?"** The Guardrails page: permissions
     are an allowlist, the hooks block specific operations deterministically,
     and the headless run has an enumerated tool allowlist with no approval
     surface. Point at the amber `allowlist` rows — that is a denial happening.
     (Add *"and `main` is protected in Actions"* **only if you actually enabled
     it** in Task 3.)
   - **"Is the incident staged?"** The scenario is constructed — say so — then
     show that the mechanism is not. `git show 8067a38` is a real one-line diff;
     the metrics come from the capacity model in
     `services/risk_gateway/simulation.py`. Volunteer the two things that are
     deliberately easier than reality: the deploy record uses the literal git
     short SHA, and `metrics.csv` carries a `cache_hit_rate` series that points
     at the cache faster than a real dashboard would. Both are demo reliability,
     not sleight of hand. Volunteering them buys you enormous credibility.
   - **"Who is accountable when it is wrong?"** The person who pressed
     **Merge**. Same as now.

3. **The result:** you can lose a live run and keep the room. That is the
   difference between a demo and a presentation.

---

# Task 14. Certification run
(Duration 00h:50m)

## Overview

End to end, timed, to a colleague playing the skeptic. No notes for the lines —
the runbook open for button labels is fine.

Your colleague's job is to interrupt with the four questions from Task 13 at
inconvenient moments, and to ask at least one thing you do not know the answer
to. *"I don't know, let me find out"* is an acceptable answer in the room, and
rehearsing saying it is worth the discomfort now.

**The 25-minute variant**, for when you are given half the time you were
promised: keep the incident-day replay, Task 7 **as the recording at 8×**, the
Task 8 guardrail beat, the merge, and Tasks 10's investigation. Skip the
contract walk-through and the productionize beat. Open with two minutes on
Guardrails and close with two.

## Steps

1. Reset and start clean:

   ```bash
   ./demo/reset-demo.sh && ./demo/up.sh
   ```

2. Run Tasks 6 → 12 in order, timed. Target 50 minutes; anything over 60 means
   you are over-explaining the features and under-showing the timeline.

3. Have your colleague score three things, and only these three:

   - Did the **guardrail beat** (Task 8) land, including both escalations?
   - Did you say **both** mechanisms in Task 10, in the right order — leakage
     first, then train/serve skew?
   - When something went wrong or ran long, did you **name it** rather than
     talk over it?

4. Run the 25-minute variant once, on a different day.

5. **The result:** you can run this demo. The three scored items are the ones
   that survive in the audience's memory a week later — the specific tool calls
   do not.

---

## Quick reference

```bash
./demo/reset-demo.sh && ./demo/up.sh    # before every run
./demo/reset-demo.sh --check            # readiness only, changes nothing
./demo/reset-demo.sh --restore-notebook # mid-demo fallback, Task 10
./demo/reset-demo.sh --restore-gates    # mid-demo fallback, Task 11
# ./demo/build_history.sh               # NOT yours to run — see Task 2
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
| Decoy commit / actual cause | `88c2501` / `8067a38` |
