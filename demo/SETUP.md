# Setup

## Prerequisites

| Tool | Why | Check |
|---|---|---|
| Claude Code, logged in | the demo | `claude -p "reply with the word OK"` prints `OK` |
| `uv` | Python deps, JupyterLab | `uv --version` |
| Node 20+ | builds the console UI (`web/`) | `node --version` |
| `git` | history is part of the incident | `git --version` |
| `gh` (optional) | only for the live GitHub Actions beats | `gh auth status` |

Python 3.11+ for the project. The guardrail hooks run under whatever
`python3` is on your `PATH` (they are stdlib-only and need 3.10+). No Docker,
no database, no network calls beyond Claude itself — every beat runs locally,
on purpose. A demo that depends on someone else's uptime is a demo that fails
in front of an audience.

## First run

```bash
cd tessera-platform
uv sync --all-groups
npm --prefix web ci && npm --prefix web run build
./demo/build_history.sh          # once: builds the demo git history and the demo-base tag
./demo/reset-demo.sh --check
```

You want green checks and `Ready.` Two warnings are expected until you record
the fallbacks (below): `no golden recording` and `no executed notebook fallback`.

## Start the demo

```bash
./demo/up.sh
```

Starts the ops console on `http://localhost:8765` and JupyterLab on
`http://localhost:8888/lab?token=tessera`, builds `web/dist` if it is stale,
and checks that headless Claude answers. `Ctrl-C` stops both. Ports:
`TESSERA_CONSOLE_PORT`, `TESSERA_JUPYTER_PORT`.

`up.sh` also sets `TESSERA_PR_PROVIDER=local`, which keeps the console's pull
requests in `.tessera/prs/` where `reset-demo.sh` can clear them. Without it the
console reads `gh pr list` instead, and since GitHub cannot delete a merged pull
request, every run would leave one on the Incidents tab for the next run to open
with. The remote is still used for the GitHub Actions beats.

Open the Claude Code desktop app on the **repository root** — `.claude/settings.json`
resolves the hooks relative to it. Starting in a subdirectory means no
guardrails, which removes the spine of use case 1.

## Record the fallbacks (once, ~25 minutes of Claude time)

With `./demo/up.sh` running, on a clean `main`:

```bash
./demo/record-golden-run.sh
```

runs one real headless triage (8–12 minutes, a few dollars) and copies the
stream, PR description and branch patch to `demo/recordings/triage-INC-4412/`.
The console's **Play recording** button plays it back at 1–16×, and playing it
restores the branch and PR so the beats after it still work.

For the notebook beat, run **Prompt 1** from the Models page once in the
desktop app, then:

```bash
cp ml/notebooks/03_v3_shadow_investigation.ipynb demo/recordings/03_v3_shadow_investigation.executed.ipynb
```

For the productionize beat, run **Prompt 2** once on a branch and keep the
result as a patch:

```bash
git checkout -b ml/tess-2310-validation-gates
# run Prompt 2 in the desktop app and let it commit on this branch
git format-patch --stdout main..HEAD > demo/recordings/ml-tess-2310.patch
git checkout main && git branch -D ml/tess-2310-validation-gates
```

Then commit the recordings: `./demo/build_history.sh` adds them in a final
commit of their own.

## Before every run

```bash
./demo/reset-demo.sh
./demo/up.sh
```

The reset backs up uncommitted work to a timestamped patch under your temp
directory (it does **not** use `git stash` — see the comment in the script),
hard-resets `main` to the `demo-base` tag (the merge in 1.6 moves `main`;
only a hard reset undoes it), deletes every other branch, clears the console's
state under `.tessera/`, regenerates the synthetic data, notebooks, incident
evidence and model registry, re-syncs the commit SHAs quoted in these docs, and
re-runs the readiness checks. It refuses to run while a headless run is active.

Arguments are exactly `--check`, `--restore-notebook`, `--restore-gates`,
`--help` or nothing; anything else prints usage and exits.

## Why Claude cannot read `demo/`

`.claude/settings.json` denies `Read` on `demo/**`. This directory is the
answer key — the runbook, the golden recording, the scripts that generate the
incident. Without the deny, an agent triaging INC-4412 can reach it from the
README link and short-circuit the investigation in one file read.

It is also a neat demonstration of the point the guardrail beat makes:
scoping an agent away from files it should not see is a two-line change,
enforced by the harness rather than by asking nicely.

If you want Claude's help editing the demo materials themselves, remove that
line from the deny list first — and put it back before you present
(`reset-demo.sh --check` asserts it is there).

## What is fictional

Tessera Financial does not exist. Every transaction, applicant, incident,
model and credential in this repository is synthetic. The `.env` file contains
placeholder values that authenticate to nothing; it exists so the secrets
guardrail has a realistic target. The commit authors are fictional too — which
matters in 1.4: `git blame` on the offending commit names a person, and the
`incident-postmortem` skill instructs Claude to write blamelessly anyway.

## Recovering mid-demo

| Problem | Do this |
|---|---|
| Live run is slow or wandering | **Cancel**, then **Play recording** at 4× — say it is a recording |
| Live run failed | the failure card's button plays the golden recording |
| Claude in the desktop app wandered off-script | `Esc` to interrupt, re-prompt more narrowly |
| JupyterLab complains the file changed on disk | choose *Revert* — Claude's version is the one you want |
| Notebook beat is running long | `./demo/reset-demo.sh --restore-notebook`, reopen the notebook |
| Productionize beat is running long | `Esc`, then `./demo/reset-demo.sh --restore-gates` and **Run validation gates** |
| Console shows `reconnecting…` | it reconnects on its own; a page reload lands on the same state |
| `up.sh` will not stop, or a port is "in use" | `pkill -9 -f "uvicorn services.console"` — a browser tab's open event stream can hold a shutdown |
| Everything is confused | new terminal: `./demo/reset-demo.sh && ./demo/up.sh` |

The captured transcripts in `demo/expected-output/` are text-only fallbacks
for talking through a beat without the UI.
