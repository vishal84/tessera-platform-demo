# Making the GitHub Actions beats live

Two beats — **1.4** (automated PR review) and **2.4** (alert-triggered triage)
— show workflow files and captured output because nothing is pushed yet. This
converts them to live runs. About ten minutes.

Everything else in the demo runs locally and needs none of this.

## 1. Create the remote

Private is enough. The audience watches your screen, not the repo.

```bash
gh repo create tessera-platform --private --source=. --push
```

Consider a personal account or a scratch org rather than a company org — the
repo contains a realistic-looking `.env` (synthetic, but it looks real) and an
incident that never happened.

## 2. Add the API key

```bash
gh secret set ANTHROPIC_API_KEY
```

This key pays for the Actions runs. Scope it to this repository.

## 3. Install the GitHub app

```bash
claude
/install-github-app
```

This is what lets `@claude` mentions and the review workflow act on PRs.

## 4. Protect main — only if your plan allows it

**Branch protection needs GitHub Pro or a public repository.** On a private
repo on the free tier both the protection API and the rulesets API return
`403 — "Upgrade to GitHub Pro or make this repository public."` Step 1 above
creates a *private* repo, so by default this step will not work.

```bash
gh api -X PUT repos/:owner/tessera-platform/branches/main/protection \
  -f "required_pull_request_reviews[required_approving_review_count]=1" \
  -F "enforce_admins=false" \
  -F "restrictions=null" \
  -F "required_status_checks=null"
```

If it succeeds, verify in Settings → Branches that direct pushes to `main` are
blocked. Being able to say "try it yourself" when someone asks is worth the two
minutes.

If it returns 403, you have three options: make the repo public (it is entirely
synthetic — see *What is fictional* in `demo/SETUP.md`), use an account with
Pro, or leave it off. **Leaving it off is fine, but then do not claim it.**
The containment that holds without it is real and is what the presenter docs
now say: the enumerated tool allowlist, the hooks on every write, no deployment
permission in the job, and a final workflow step that re-runs both hooks and
fails the run if a protected path moved. Verify which state you are in:

```bash
gh api repos/{owner}/{repo}/branches/main/protection >/dev/null 2>&1 \
  && echo "protected — you may say so" \
  || echo "NOT protected — do not claim it"
```

## 5. Verify both beats

**Beat 1.4** — push a branch with a deliberate PCI violation and confirm the
review catches it:

```bash
git checkout -b demo/verify-review
cat >> services/payments_api/service.py <<'EOF'

def _debug_capture(card_number: str) -> None:
    logger.info("capturing card %s", card_number)  # reviewer should catch this
EOF
git add -A && git commit -m "chore: temporary debug logging"
git push -u origin demo/verify-review && gh pr create --fill
```

Two things should happen: CI fails on the cardholder-data check, and the
Claude review posts an inline comment on that line. Then:

```bash
git checkout main && git branch -D demo/verify-review
git push origin --delete demo/verify-review
```

**Beat 2.4** — fire the dispatch:

```bash
gh workflow run claude-incident-fix.yml -f incident_id=INC-4412
gh run watch
```

It should open a PR. Confirm it did **not** push to `main`.

## 6. Update the runbook

In `demo/DEMO_RUNBOOK.md`, beats 1.4 and 2.4 say to fall back to
`demo/expected-output/`. Replace that with the live steps above.

## Resetting between runs

Live runs leave PRs and branches behind:

```bash
gh pr list --json number --jq '.[].number' | xargs -n1 gh pr close --delete-branch
./demo/reset-demo.sh
```

## If you would rather not push at all

Perfectly reasonable, and the demo still works. Show the workflow files —
`claude-incident-fix.yml` is genuinely interesting to read, especially the
permissions block and the final guardrail step — and walk the captured output.
The audience is evaluating the shape of the workflow, not whether a runner
executed it in front of them.

Say plainly that it is captured output. Presenting a recording as a live run
is the kind of thing that gets noticed, and it costs you the room.


## The console after you push

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
