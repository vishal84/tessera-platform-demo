#!/usr/bin/env bash
#
# Reset the demo to its starting state, or check that it is ready.
#
#   ./demo/reset-demo.sh                    reset (see below) then run the readiness checks
#   ./demo/reset-demo.sh --check            readiness checks only; changes nothing
#   ./demo/reset-demo.sh --restore-notebook put the executed fallback notebook in place (mid-demo)
#   ./demo/reset-demo.sh --restore-gates    recreate the productionized branch from the recorded run (mid-demo)
#   ./demo/reset-demo.sh --adopt-base       re-anchor demo-base on main, so setup commits survive every reset
#   ./demo/reset-demo.sh --help
#
# A reset backs up uncommitted work to a patch outside the repository, then
# hard-resets to the `demo-base` tag (the merged incident PR moves main; only
# a hard reset undoes that), deletes every other branch, clears the console's
# runtime state under .tessera/, regenerates the synthetic data, notebooks,
# incident evidence and model registry, and re-syncs the commit SHAs quoted in
# the presenter docs. It never touches .venv/, web/node_modules/ or .tessera/logs/.

set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok   () { printf "  ${GREEN}ok${OFF}    %s\n" "$1"; }
warn () { printf "  ${YELLOW}warn${OFF}  %s\n" "$1"; }
fail () { printf "  ${RED}FAIL${OFF}  %s\n" "$1"; FAILED=1; }
FAILED=0
CONSOLE="http://localhost:${TESSERA_CONSOLE_PORT:-8765}"
JUPYTER="http://localhost:${TESSERA_JUPYTER_PORT:-8888}"

usage () { sed -n '3,11p' "$0" | sed 's/^#//'; }

# Paths that belong to the presenter's toolchain rather than to the demo story.
# A reset rewinds main to demo-base and would discard changes to these, so
# --adopt-base folds their current state into the tag instead.
# docs/egress.md is listed because adding an MCP server is a new outbound
# destination and CLAUDE.md requires it to be recorded there -- config and
# its justification have to survive together. The rest of docs/ is not listed:
# docs/config.md is edited during the guardrail beat and is demo residue.
# ml/notebooks/01 is a build artifact of demo/build_notebook.py, but it is also
# committed -- and the reset runs `git checkout -- .` after regenerating, which
# reverts anything differing from HEAD. So the generator and its output have to
# enter the base together, or the reset silently restores a stale notebook.
# Only that one notebook: 03 is reseeded per run and 02 is hand-written.
ADOPT_PATHS=(.github/ .mcp.json .claude/settings.json pyproject.toml uv.lock demo/ docs/egress.md
             ml/notebooks/01_fraud_exploration.ipynb services/console/ web/)
# services/console/ and web/ are the console itself -- stage furniture, never
# incident state, so the tag should carry the current version. services/ as a
# whole must NOT be adopted: services/risk_gateway/config.py holds the unfixed
# incident that demo-base exists to preserve.

MODE="${1:-reset}"
case "$MODE" in
  reset|--reset) MODE=reset ;;
  --check) MODE=check ;;
  --restore-notebook) MODE=restore ;;
  --restore-gates) MODE=restore_gates ;;
  --adopt-base) MODE=adopt_base ;;
  -h|--help) usage; exit 0 ;;
  *) echo "unknown argument: $MODE"; usage; exit 2 ;;
esac

if [[ $MODE == restore ]]; then
  src=demo/recordings/03_v3_shadow_investigation.executed.ipynb
  [[ -f $src ]] || { fail "no executed fallback at $src -- record one first (DEMO_RUNBOOK.md 1.4)"; exit 1; }
  cp "$src" ml/notebooks/03_v3_shadow_investigation.ipynb && ok "executed notebook restored; reopen it in JupyterLab"
  exit 0
fi

if [[ $MODE == restore_gates ]]; then
  src=demo/recordings/ml-tess-2310.patch
  branch=ml/tess-2310-validation-gates
  [[ -f $src ]] || { fail "no gates fallback at $src -- record one first (DEMO_RUNBOOK.md 1.4)"; exit 1; }
  [[ -z "$(git status --porcelain)" ]] || { fail "working tree has uncommitted changes; commit or discard them first"; exit 1; }
  git checkout -q main
  git branch -q -D "$branch" >/dev/null 2>&1 || true
  if git checkout -q -b "$branch" main && git am -q "$src"; then
    ok "restored $branch from the recorded run; the tree is on it -- press Run validation gates"
  else
    git am --abort >/dev/null 2>&1 || true; git checkout -q main; git branch -q -D "$branch" >/dev/null 2>&1 || true
    fail "the recorded patch did not apply to main"; exit 1
  fi
  exit 0
fi

if [[ $MODE == adopt_base ]]; then
  # Re-anchor demo-base so toolchain setup survives every reset. A reset
  # rewinds main to this tag, so a CI workflow fix, .mcp.json or a dependency
  # bump committed afterwards is discarded -- and re-running build_history.sh
  # to bake it in would delete .git and the GitHub setup with it.
  #
  # Only commits touching the toolchain are carried over. Demo residue (the
  # merged incident PR) is deliberately left behind: the tag has to keep
  # describing the state the demo starts from, with the incident unfixed.
  git rev-parse --verify --quiet demo-base >/dev/null \
    || { fail "no demo-base tag -- run ./demo/build_history.sh once first"; exit 1; }
  [[ -z "$(git status --porcelain)" ]] \
    || { fail "working tree has uncommitted changes -- commit or discard them first"; exit 1; }

  # Snapshot the toolchain paths as they stand now onto demo-base, as one
  # commit. Replaying the individual commits instead would conflict as soon as
  # one of them had already been folded in under a different SHA.
  WT="$(mktemp -d)/base"
  git worktree add -q --detach "$WT" demo-base \
    || { fail "could not create a scratch worktree"; exit 1; }
  discard () { git worktree remove --force "$WT" >/dev/null 2>&1 || true; git worktree prune; }

  git -C "$WT" checkout "$(git rev-parse HEAD)" -- "${ADOPT_PATHS[@]}" 2>/dev/null || true
  if git -C "$WT" diff --cached --quiet; then
    discard; ok "demo-base already matches the toolchain on $(git rev-parse --abbrev-ref HEAD)"; exit 0
  fi

  # The tag has to keep describing a tree with the incident in it, or there is
  # nothing for the SRE beat to investigate.
  if ! grep -q 'CACHE_TTL_SECONDS = 0' "$WT/services/risk_gateway/config.py"; then
    discard; fail "the incident is not present at the new base -- refusing to anchor there"; exit 1
  fi

  echo "  folding in:"
  git -C "$WT" diff --cached --stat | sed 's/^/    /'
  git -C "$WT" commit -q -m "chore(demo): adopt toolchain state into the demo base" \
    -m "Workflows, MCP config, permissions, dependencies and the demo harness as
they stand on the presenter's branch, folded into the tag reset-demo.sh
rewinds to. The demo story itself is unchanged: the incident is still
unfixed at this commit."
  PREV=$(git rev-parse --short demo-base)
  git tag -f demo-base "$(git -C "$WT" rev-parse HEAD)" >/dev/null
  discard
  ok "demo-base re-anchored: $PREV -> $(git rev-parse --short demo-base)"
  exit 0
fi

if [[ $MODE == reset ]]; then
  echo "Resetting demo state"

  if curl -sf "$CONSOLE/api/health" 2>/dev/null | grep -q '"active": *true'; then
    fail "a headless run is active in the console -- cancel it first"; exit 1
  fi

  # The reset rewinds main to demo-base. Losing the merged incident PR is the
  # point; losing the presenter's own toolchain setup is not. Compare content,
  # not history: a toolchain commit already folded into demo-base by
  # --adopt-base still appears in demo-base..main under its old SHA, but
  # discarding it loses nothing. This stays quiet on an ordinary reset.
  if git rev-parse --verify --quiet demo-base >/dev/null \
     && ! git diff --quiet demo-base main -- "${ADOPT_PATHS[@]}" 2>/dev/null; then
    warn "toolchain files on main differ from demo-base, and the reset overwrites them:"
    git diff --stat demo-base main -- "${ADOPT_PATHS[@]}" | sed 's/^/          /'
    warn "keep them instead with: ./demo/reset-demo.sh --adopt-base"
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    # Deliberately NOT `git stash`: demo/build_history.sh rebuilds history with
    # `rm -rf .git`, which destroys stashes. A patch outside the repo survives that.
    BACKUP="${TMPDIR:-/tmp}/tessera-demo-$(date +%Y%m%d-%H%M%S).patch"
    git diff HEAD > "$BACKUP"
    git ls-files --others --exclude-standard | tar -cf "${BACKUP%.patch}-untracked.tar" -T - 2>/dev/null || true
    warn "uncommitted changes backed up to $BACKUP"
  fi

  git reset -q --hard HEAD
  git checkout -q main 2>/dev/null || git checkout -q -b main
  if git rev-parse --verify --quiet demo-base >/dev/null; then
    git reset -q --hard demo-base && ok "main reset to demo-base ($(git rev-parse --short demo-base))"
  else
    warn "no demo-base tag -- run ./demo/build_history.sh once; leaving main at HEAD"
  fi
  git clean -qfd
  for b in $(git branch --format='%(refname:short)' | grep -Ev '^main$' || true); do
    git branch -q -D "$b" && ok "deleted branch $b"
  done

  rm -rf .tessera/runs .tessera/prs .tessera/audit.jsonl .tessera/events.jsonl .tessera/run.lock \
         ml/artifacts .pytest_cache fairness.md
  find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
  find . -name .ipynb_checkpoints -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find ml services web/src -type d -empty -delete 2>/dev/null || true   # e.g. ml/validation/ left by a fallback restore
  ok "cleared console state (.tessera/) and build artifacts"

  uv run --quiet python ml/data/generate.py >/dev/null           && ok "regenerated synthetic data"
  uv run --quiet python demo/build_notebook.py >/dev/null        && ok "rebuilt exploration notebook (01)"
  uv run --quiet python demo/generate_incident.py >/dev/null     && ok "regenerated INC-4412 evidence"
  uv run --quiet python demo/generate_shadow_report.py >/dev/null && ok "regenerated model registry and shadow report"
  uv run --quiet python demo/build_notebook_03.py >/dev/null     && ok "reseeded investigation notebook (03)"
  uv run --quiet python demo/sync_shas.py | sed 's/^/  /' \
    || fail "could not sync commit SHAs into the presenter docs"
  git checkout -q -- . 2>/dev/null || true     # regeneration is deterministic; nothing should differ
  echo
fi

echo "Readiness checks"

# --- guardrails ---------------------------------------------------------------
# These probes must not land in the live audit trail the console shows.
export TESSERA_AUDIT_DISABLE=1
python3 .claude/hooks/protect_secrets.py --selftest >/dev/null 2>&1 \
  && ok "secrets guardrail passes selftest" || fail "secrets guardrail selftest"
python3 .claude/hooks/pii_scan.py --selftest >/dev/null 2>&1 \
  && ok "cardholder-data scanner passes selftest" || fail "PII scanner selftest"
printf '{"tool_name":"Write","tool_input":{"file_path":".env"}}' \
  | python3 .claude/hooks/protect_secrets.py >/dev/null 2>&1 \
  && fail ".env write was ALLOWED -- the guardrail beat will not land" \
  || ok ".env write is blocked (the guardrail beat)"
[[ -f .env ]] && ok ".env present (the guardrail needs a target)" || fail ".env missing"
AUDIT_TMP=$(mktemp -d)
printf '{"session_id":"check","hook_event_name":"PreToolUse","cwd":"%s","tool_name":"Write","tool_input":{"file_path":".env"}}' "$PWD" \
  | TESSERA_AUDIT_DISABLE= TESSERA_AUDIT_DIR="$AUDIT_TMP" python3 .claude/hooks/protect_secrets.py >/dev/null 2>&1 || true
[[ -s "$AUDIT_TMP/.tessera/audit.jsonl" ]] \
  && ok "hooks write the audit trail (the Guardrails page feed)" \
  || fail "hooks did not write an audit line"
rm -rf "$AUDIT_TMP"
grep -q '"Read(./demo/\*\*)"' .claude/settings.json \
  && ok "demo/ is read-denied to the agent (the answer key stays closed)" \
  || fail "settings.json no longer denies Read on demo/**"

# --- repository -----------------------------------------------------------------
[[ "$(git branch --show-current)" == main ]] && ok "on main" || fail "not on main ($(git branch --show-current))"
[[ -z "$(git status --porcelain)" ]] && ok "working tree clean" || warn "working tree has uncommitted changes (a live run refuses to start)"
git rev-parse --verify --quiet demo-base >/dev/null && ok "demo-base tag present" || warn "no demo-base tag (run ./demo/build_history.sh)"
if git remote get-url origin >/dev/null 2>&1; then
  ok "origin remote present (the GitHub Actions beats can run)"
else
  warn "no origin remote -- the Actions beats fall back to captured output (demo/DEMO_RUNBOOK.md 1.6)"
fi
[[ -z "$(git branch --list 'incident/*')" ]] && ok "no leftover incident branches" || fail "incident branch present: $(git branch --list 'incident/*' | tr -d ' ')"

DEPLOYED=$(git log --format=%h -1 --grep="note fail-closed semantics")
CAUSE=$(git log --format=%h -1 --grep="reduce risk-gateway pod memory")
if [[ -n "$DEPLOYED" ]] && grep -q "$DEPLOYED" ops/incidents/INC-4412/deploys.txt; then
  ok "deploy record names $DEPLOYED, which is NOT the cause (the triage chain)"
else
  fail "deploy timeline does not reference the deployed revision"
fi
if [[ -n "$CAUSE" ]] && ! grep -q "$CAUSE" ops/incidents/INC-4412/deploys.txt \
   && ! grep -q "$CAUSE" ops/incidents/INC-4412/logs.jsonl; then
  ok "the causing commit $CAUSE appears nowhere in the evidence bundle"
else
  fail "evidence bundle names the causing commit -- triage is a lookup, not an investigation"
fi

uv run --quiet python -m services.risk_gateway.simulation --json 2>/dev/null \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; sys.exit(0 if r['utilization']>1.0 and r['mean_attempts_per_call']>2.0 else 1)" \
  && ok "incident conditions reproduce from live config (production tiles are red)" \
  || fail "live config is healthy -- there is nothing to investigate"

# --- tests --------------------------------------------------------------------------
TESSERA_AUDIT_DISABLE=1 uv run --quiet pytest -q >/dev/null 2>&1 \
  && ok "test suite green" || fail "test suite is not green"

# --- data science beat --------------------------------------------------------------
python3 -c "
import json,sys
nb=json.load(open('ml/notebooks/01_fraud_exploration.ipynb'))
src=' '.join(''.join(c['source']) for c in nb['cells'])
sys.exit(0 if 'card_chargeback_rate' in src else 1)" \
  && ok "leaky feature present in notebook 01" || fail "leaky feature missing from notebook 01"
python3 -c "
import json,sys
r=json.load(open('ml/registry/shadow/fraud-v3-candidate.json'))
sys.exit(0 if r['shadow']['auc'] < r['champion_same_window']['auc'] < r['offline']['auc'] else 1)" 2>/dev/null \
  && ok "shadow report: shadow < champion < offline (the Models page has a story)" \
  || fail "model registry missing or numbers do not tell the story"
python3 -c "
import json,sys
nb=json.load(open('ml/notebooks/03_v3_shadow_investigation.ipynb'))
sys.exit(0 if len(nb['cells'])==5 and all(c.get('id') for c in nb['cells']) else 1)" 2>/dev/null \
  && ok "investigation notebook (03) is the 5-cell seed" || fail "notebook 03 is not the seed (reset regenerates it)"
[[ -n "$(ls ml/validation/*.py 2>/dev/null)" ]] && warn "ml/validation/ exists -- the gates will not read NOT IMPLEMENTED" \
  || ok "ml/validation/ absent (gates read NOT IMPLEMENTED until the DS beat)"
[[ -f ml/fraud/MODEL_CARD.md ]] && warn "model card already present" || ok "no model card yet"

# --- console & tooling --------------------------------------------------------------------
command -v node >/dev/null && ok "node $(node --version)" || fail "node is not installed (web/ needs it)"
[[ -f web/dist/index.html ]] && ok "web/dist is built" || warn "web/dist not built (./demo/up.sh builds it)"
if out=$(claude -p "reply with the word OK" --max-turns 1 2>&1) && [[ "$out" == *OK* ]]; then
  ok "claude -p answers (logged in)"
else
  fail "claude -p is not working -- log in first"
fi
[[ -f demo/recordings/triage-INC-4412/run.jsonl && -f demo/recordings/triage-INC-4412/branch.patch ]] \
  && ok "golden triage recording present (the fallback)" \
  || warn "no golden recording (./demo/record-golden-run.sh after ./demo/up.sh)"
[[ -f demo/recordings/validate-fraud-v3-candidate/run.jsonl && -f demo/recordings/validate-fraud-v3-candidate/branch.patch ]] \
  && ok "golden model recording present (Models page, Play recording)" \
  || warn "no golden model recording (record one from the Models page, then promote it)"
[[ -f demo/recordings/03_v3_shadow_investigation.executed.ipynb ]] \
  && ok "executed notebook fallback present" || warn "no executed notebook fallback"
[[ -f demo/recordings/ml-tess-2310.patch ]] \
  && ok "productionized-branch fallback present (--restore-gates)" || warn "no gates fallback patch"
curl -sf "$CONSOLE/api/health" >/dev/null 2>&1 && ok "console reachable at $CONSOLE" || warn "console not running ($CONSOLE) -- ./demo/up.sh"
curl -sf "$JUPYTER/api" >/dev/null 2>&1 && ok "JupyterLab reachable at $JUPYTER" || warn "JupyterLab not running ($JUPYTER) -- ./demo/up.sh"

echo
if [[ $FAILED -eq 0 ]]; then
  printf "${GREEN}Ready.${OFF}  ${DIM}Open demo/DEMO_RUNBOOK.md and start at the Opening.${OFF}\n"
else
  printf "${RED}Not ready -- see failures above.${OFF}\n"; exit 1
fi
