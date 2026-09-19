#!/usr/bin/env bash
#
# Start everything the UI-driven demo needs and keep it running.
#
#   ./demo/up.sh            start the console and JupyterLab; Ctrl-C stops both
#   ./demo/up.sh --check    preflight only (deps, frontend build, claude auth, ports)
#
# Ports: TESSERA_CONSOLE_PORT (8765) and TESSERA_JUPYTER_PORT (8888).

set -euo pipefail
cd "$(dirname "$0")/.."

CONSOLE_PORT="${TESSERA_CONSOLE_PORT:-8765}"
JUPYTER_PORT="${TESSERA_JUPYTER_PORT:-8888}"
TOKEN="${TESSERA_JUPYTER_TOKEN:-tessera}"
LOGS=.tessera/logs
mkdir -p "$LOGS"

GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step () { printf "  ${GREEN}·${OFF} %s\n" "$1"; }
die  () { printf "  ${RED}x${OFF} %s\n" "$1"; exit 1; }

# 1. Python dependencies, including the notebooks group JupyterLab lives in.
uv sync --quiet --all-groups && step "python deps in sync"

# 2. Frontend: build when missing or older than its sources.
if [[ ! -f web/dist/index.html ]] || \
   [[ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit 2>/dev/null)" ]]; then
  [[ -d web/node_modules ]] || npm --prefix web ci --no-audit --no-fund --loglevel=error
  npm --prefix web run build --silent >/dev/null && step "web/dist built"
else
  step "web/dist is current"
fi

# 3. Headless Claude must actually answer -- `claude --version` succeeds logged out.
if out=$(claude -p "reply with the word OK" --max-turns 1 2>&1) && [[ "$out" == *OK* ]]; then
  step "claude -p answers (logged in)"
else
  die "claude -p is not working -- run \`claude\` once and log in. Output: ${out:0:200}"
fi

# 4. Ports.
for p in "$CONSOLE_PORT" "$JUPYTER_PORT"; do
  lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && die "port $p is already in use (TESSERA_CONSOLE_PORT / TESSERA_JUPYTER_PORT override)"
done
step "ports $CONSOLE_PORT and $JUPYTER_PORT are free"

[[ "${1:-}" == "--check" ]] && { printf "${GREEN}up.sh preflight ok${OFF}\n"; exit 0; }

# 5. JupyterLab settings: autosave off, so Claude's edits to the notebook on
#    disk never race a browser autosave. Kept out of the tree, under .tessera/.
SETTINGS=.tessera/jupyter/user-settings/@jupyterlab/docmanager-extension
mkdir -p "$SETTINGS"
printf '{ "autosave": false }\n' > "$SETTINGS/plugin.jupyterlab-settings"

# 6. Start both.
# TESSERA_PR_PROVIDER=local: the repo has a remote for the Actions beats, but the
# console's pull requests stay in .tessera/prs/ so a reset can actually clear them.
TESSERA_CONSOLE_PORT="$CONSOLE_PORT" TESSERA_JUPYTER_PORT="$JUPYTER_PORT" TESSERA_JUPYTER_TOKEN="$TOKEN" \
  TESSERA_PR_PROVIDER="${TESSERA_PR_PROVIDER:-local}" \
  uv run uvicorn services.console.app:create_app --factory --port "$CONSOLE_PORT" --log-level warning \
    --timeout-graceful-shutdown 3 \
  >"$LOGS/console.log" 2>&1 &
CONSOLE_PID=$!

JUPYTERLAB_SETTINGS_DIR=.tessera/jupyter/user-settings \
  uv run --group notebooks jupyter lab --no-browser --port "$JUPYTER_PORT" \
  --IdentityProvider.token="$TOKEN" --ServerApp.root_dir=. --ServerApp.open_browser=False \
  >"$LOGS/jupyter.log" 2>&1 &
JUPYTER_PID=$!

# An open browser stream keeps uvicorn's graceful shutdown waiting; the
# --timeout-graceful-shutdown above bounds that, and this bounds everything else.
cleanup () {
  kill "$CONSOLE_PID" "$JUPYTER_PID" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$CONSOLE_PID" 2>/dev/null || kill -0 "$JUPYTER_PID" 2>/dev/null || break; sleep 0.25; done
  kill -9 "$CONSOLE_PID" "$JUPYTER_PID" 2>/dev/null || true
  wait 2>/dev/null || true; echo; echo "stopped"
}
trap cleanup INT TERM EXIT

for _ in $(seq 1 40); do
  curl -sf "http://localhost:$CONSOLE_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -sf "http://localhost:$CONSOLE_PORT/api/health" >/dev/null || die "console did not start -- see $LOGS/console.log"

echo
printf "  console    ${GREEN}http://localhost:%s${OFF}\n" "$CONSOLE_PORT"
printf "  jupyterlab ${GREEN}http://localhost:%s/lab?token=%s${OFF}\n" "$JUPYTER_PORT" "$TOKEN"
printf "  logs       ${DIM}%s/{console,jupyter}.log${OFF}\n" "$LOGS"
echo
echo "Ctrl-C stops both."
wait
