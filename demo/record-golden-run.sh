#!/usr/bin/env bash
#
# Capture a live headless triage as the committed on-stage fallback.
#
#   ./demo/record-golden-run.sh [INC-4412]
#
# Needs: the console running (./demo/up.sh), a clean tree on main, and a
# logged-in `claude`. Takes 6-12 minutes and costs real API money. When it
# finishes, the recording (stream, PR description, branch bundle) is copied to
# demo/recordings/triage-<id>/ and the repo is put back the way it was so the
# recording can be committed on its own.

set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${TESSERA_CONSOLE_PORT:-8765}"
INC="${1:-INC-4412}"

json () { python3 -c "import json,sys; d=json.load(sys.stdin); print(d$1)"; }

response=$(curl -s -X POST "http://localhost:$PORT/api/runs" -H 'content-type: application/json' \
           -d "{\"incident_id\":\"$INC\",\"mode\":\"live\",\"record\":true}")
run_id=$(json "['run_id']" <<<"$response" 2>/dev/null) || { echo "could not start a run: $response"; exit 1; }
echo "run $run_id started -- watch it at http://localhost:$PORT/incidents/$INC"

while :; do
  status=$(curl -s "http://localhost:$PORT/api/runs/$run_id" | json "['status']")
  [[ "$status" == "running" ]] || break
  sleep 5
done
meta=$(curl -s "http://localhost:$PORT/api/runs/$run_id")
branch=$(json "['branch']" <<<"$meta"); pr=$(json "['pr_id']" <<<"$meta")
echo "status=$status branch=$branch pr=$pr"
[[ "$status" == "finished" && "$pr" != "None" ]] || { echo "not a usable recording; try again"; exit 1; }

dest="demo/recordings/triage-$INC"
rm -rf "$dest"; mkdir -p demo/recordings
cp -R ".tessera/runs/$run_id" "$dest"
# The run narrates commit SHAs; record which ones were current so a history
# rebuild can rewrite them (demo/sync_shas.py).
cp demo/.sha-state.json "$dest/sha-state.json"
echo "captured to $dest"

# Put the repository back: the recording restores the branch and PR on replay.
git checkout -q main
git branch -D "$branch" >/dev/null
rm -f ".tessera/prs/$(echo "$branch" | sed 's#/#__#g').md"
echo "repo reset to main; commit $dest as its own commit (see demo/build_history.sh)"
