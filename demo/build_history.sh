#!/usr/bin/env bash
#
# Rebuild the demo repository's git history from the current working tree.
#
# The history is part of the demo: Act 2 depends on being able to correlate a
# deploy timestamp to a commit and read its diff. Three commits touch
# risk-gateway on the day of the incident and only one of them explains it, so
# the responder has to read the diffs rather than pick the only candidate.
#
# Destructive -- deletes .git and rebuilds. Run from the repo root.

set -euo pipefail
cd "$(dirname "$0")/.."

# Setup, not a per-run step. Deleting .git destroys the `origin` remote, and
# with it the link to the GitHub repository that holds ANTHROPIC_API_KEY, the
# branch protection on main and the installed GitHub App -- so a presenter who
# runs this by mistake has to redo the push setup before the Actions beats work
# again. Between demo runs use ./demo/reset-demo.sh, which keeps all of it.
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1
if [[ -d .git && $FORCE -eq 0 ]]; then
  cat >&2 <<'MSG'
Refusing to rebuild: .git already exists.

  ./demo/reset-demo.sh             reset between runs -- keeps .git, the remote
                                   and everything set up on the GitHub side
  ./demo/build_history.sh --force  really delete .git and rebuild the history

A rebuild changes every commit SHA and drops local branches and tags. Remotes
are saved and restored, but the first push afterwards must be a force-push.
MSG
  exit 1
fi

# Saved across the rebuild so the GitHub setup does not have to be redone.
REMOTES=""
[[ -d .git ]] && REMOTES=$(git remote -v | awk '$3 == "(fetch)" { print $1, $2 }')

rm -rf .git
git init -q -b main
git config user.name "Tessera CI"
git config user.email "ci@tessera.test"
git config commit.gpgsign false

c () { local d="$1" an="$2" ae="$3"; shift 3
  GIT_AUTHOR_DATE="$d" GIT_COMMITTER_DATE="$d" GIT_AUTHOR_NAME="$an" GIT_AUTHOR_EMAIL="$ae" \
  GIT_COMMITTER_NAME="$an" GIT_COMMITTER_EMAIL="$ae" git commit -q "$@"; }

set_cfg () { python3 -c "
import pathlib,sys
p=pathlib.Path('services/risk_gateway/config.py')
s=p.read_text().replace(sys.argv[1], sys.argv[2])
p.write_text(s)" "$1" "$2"; }

# Generated artefacts that are committed: registry + shadow report, notebook 03.
# Deterministic, so re-running produces byte-identical files and stable SHAs.
uv run --quiet python demo/generate_shadow_report.py >/dev/null
uv run --quiet python demo/build_notebook_03.py >/dev/null

# Rewind the working tree to its pre-incident state so the commits below are
# real diffs. This must be idempotent -- the script is run repeatedly.
set_cfg "CACHE_TTL_SECONDS = 0"   "CACHE_TTL_SECONDS = 300"
set_cfg "MAX_CONNECTIONS = 512"   "MAX_CONNECTIONS = 256"
python3 - <<'PY'
import pathlib
p = pathlib.Path("services/risk_gateway/client.py")
p.write_text(p.read_text().replace(
    '        """Score a transaction. Raises rather than returning a decision on failure."""\n', ''))
PY

git add CLAUDE.md README.md pyproject.toml uv.lock .gitignore .env .env.example services/__init__.py
c "2026-01-14T09:12:00Z" "Dan Okafor" "dan@tessera.test" -m "chore: platform scaffold and conventions"

git add services/ledger/
c "2026-01-22T14:40:00Z" "Mei Lin" "mei@tessera.test" \
  -m "feat(ledger): double-entry core with balance invariants" \
  -m "Debits must equal credits at construction. Posted entries are frozen; corrections are compensating entries."

git add services/risk_gateway/
c "2026-02-03T11:05:00Z" "Dan Okafor" "dan@tessera.test" -m "feat(risk): fraud model gateway with response cache"

git add services/payments_api/ migrations/
c "2026-02-19T16:28:00Z" "Mei Lin" "mei@tessera.test" -m "feat(payments): authorize, capture and full refunds"

git add ml/data/ ml/features/ ml/__init__.py ml/README.md ml/fraud/ ml/profiles/__init__.py
c "2026-04-08T10:15:00Z" "Priya Raman" "priya@tessera.test" -m "chore(ml): synthetic data generator and base feature module"

git add docs/ ops/slo.yaml ops/runbooks/
c "2026-05-21T13:02:00Z" "Dan Okafor" "dan@tessera.test" -m "docs: architecture, config, egress and risk-gateway runbook"

git add .claude/ ':!.claude/launch.json'
c "2026-06-30T15:44:00Z" "Mei Lin" "mei@tessera.test" \
  -m "chore(claude): guardrails, subagents, skills and commands" \
  -m "Secrets and cardholder-data hooks run identically in a local session and in CI."

git add .github/
c "2026-07-15T09:30:00Z" "Dan Okafor" "dan@tessera.test" -m "ci: tests, guardrail selftests and automated review"

git add ml/notebooks/01_fraud_exploration.ipynb ml/notebooks/02_credit_scoring_draft.ipynb ml/profiles/
c "2026-09-10T17:20:00Z" "Priya Raman" "priya@tessera.test" -m "chore(ml): fraud v3 exploration notebook and behaviour profiles"

# The model platform's shadow run of the candidate: the numbers the data
# scientist receives, plus the notebook she opens to look into them.
git add ml/registry/ ml/notebooks/03_v3_shadow_investigation.ipynb
c "2026-09-16T09:00:00Z" "Priya Raman" "priya@tessera.test" \
  -m "chore(ml): register fraud-v3-candidate shadow run" \
  -m "Promotion blocked by the model platform: shadow AUC below the champion on the same window.

Ref: TESS-2310"

# --- incident day: three commits to risk-gateway, one deploy at 14:02 -------

# Decoy. A plausible perf change to the same file, and genuinely a
# contributing factor -- a larger pool keeps more doomed requests in flight.
set_cfg "MAX_CONNECTIONS = 256" "MAX_CONNECTIONS = 512"
git add services/risk_gateway/config.py
c "2026-09-17T11:20:00Z" "Dan Okafor" "dan@tessera.test" \
  -m "perf: raise risk-gateway connection pool limit" \
  -m "Seeing pool-wait warnings at peak. Doubling to 512.

Ref: TESS-2279"

# The one that actually explains the incident.
set_cfg "CACHE_TTL_SECONDS = 300" "CACHE_TTL_SECONDS = 0"
git add services/risk_gateway/config.py
c "2026-09-17T13:58:00Z" "Priya Raman" "priya@tessera.test" \
  -m "perf: reduce risk-gateway pod memory footprint" \
  -m "Risk-gateway pods have been sitting at ~400MB resident and tripping the
overnight memory-pressure alert twice a week. This frees the largest
allocation. Latency headroom on the dependency is fine, so this should be
neutral for the auth path.

Ref: TESS-2287"

# Decoy, and the one that matters structurally. This lands last, so it is
# HEAD when the 14:02 deploy goes out and it is the revision the deploy
# record and the config-reload log both name. An investigator who assumes
# deploy-HEAD is the cause gets a docstring and has to start over.
python3 -c "
import pathlib
p = pathlib.Path('services/risk_gateway/client.py')
s = p.read_text()
s = s.replace(
    '    def score(self, *, card_token: str, amount_minor: int, currency: str) -> RiskDecision:\n        key',
    '''    def score(self, *, card_token: str, amount_minor: int, currency: str) -> RiskDecision:
        \"\"\"Score a transaction. Raises rather than returning a decision on failure.\"\"\"
        key''')
p.write_text(s)"
git add services/risk_gateway/client.py
c "2026-09-17T14:00:00Z" "Mei Lin" "mei@tessera.test" -m "docs(risk): note fail-closed semantics on score()"

git add ops/incidents/
c "2026-09-17T15:05:00Z" "Dan Okafor" "dan@tessera.test" \
  -m "chore(ops): capture INC-4412 evidence bundle" \
  -m "Mitigated by shifting traffic. Root cause still open."

git add -A -- . ':!demo/recordings'
c "2026-09-19T12:00:00Z" "Tessera CI" "ci@tessera.test" \
  -m "chore: ops console, demo harness and runbook" \
  -m "services/console serves the Tessera Ops Console (web/) and runs the same headless triage the incident workflow does."

# The evidence bundle references real commit SHAs, so it must be regenerated
# after the history exists, then amended into the final commit.
uv run --quiet python demo/generate_incident.py >/dev/null

# Rebuilding history changes every SHA, and the presenter docs quote them.
# Without this the runbook silently goes stale one rebuild after being correct.
uv run --quiet python demo/sync_shas.py >/dev/null

git add ops/incidents/ demo/ ':!demo/recordings'
GIT_AUTHOR_DATE="2026-09-19T12:00:00Z" GIT_COMMITTER_DATE="2026-09-19T12:00:00Z" \
GIT_AUTHOR_NAME="Tessera CI" GIT_AUTHOR_EMAIL="ci@tessera.test" \
GIT_COMMITTER_NAME="Tessera CI" GIT_COMMITTER_EMAIL="ci@tessera.test" \
git commit -q --amend --no-edit

# Recorded fallbacks go in a commit of their own, so the demo harness commit
# is the same whether or not a recording exists yet.
if [[ -d demo/recordings ]] && [[ -n "$(ls -A demo/recordings 2>/dev/null)" ]]; then
  git add demo/recordings
  c "2026-09-19T18:00:00Z" "Tessera CI" "ci@tessera.test" \
    -m "chore(demo): recorded fallbacks for the stage" \
    -m "A headless triage run (stream, PR description, branch patch) and the executed investigation notebook."
fi

# The anchor demo/reset-demo.sh hard-resets to. Merging the incident PR moves
# main; nothing short of a hard reset undoes that.
git tag -f demo-base >/dev/null

# Put back the remotes saved before the rebuild. The history is new, so the
# first push has to be `git push --force-with-lease origin main`.
if [[ -n "$REMOTES" ]]; then
  while read -r name url; do
    [[ -n "$name" ]] && git remote add "$name" "$url" 2>/dev/null || true
  done <<< "$REMOTES"
  echo "Restored remote(s): $(git remote | tr '\n' ' ')-- force-push to publish the new history."
fi

echo "History rebuilt."
git log --date=short --pretty=format:"  %h %ad %<(14)%an %s"
echo
