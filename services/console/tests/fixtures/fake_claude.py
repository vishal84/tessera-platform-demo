#!/usr/bin/env python3
"""
Stands in for `claude -p` in tests: replays a stream-json fixture with the
requested --session-id, a small delay per line, and -- when asked -- the side
effects a real run has on the repository (a branch, a commit, a PR file).
Failure modes are selectable with TESSERA_FAKE_FAIL.

Which fixture depends on the prompt it was given, not on an env var, so it
responds to its arguments the way the real binary does and every existing test
keeps working untouched.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "stream_json_sample.jsonl"
MODEL_FIXTURE = HERE / "stream_json_model_sample.jsonl"
BRANCH = "incident/INC-4412-cache-ttl"
MODEL_BRANCH = "ml/TESS-2310-point-in-time-features"
FIXED_CONFIG = """CACHE_TTL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 1.0
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_BASE_SECONDS = 0.05
RETRY_JITTER = True
MAX_CONNECTIONS = 256
CIRCUIT_BREAKER_ENABLED = True
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.5
CIRCUIT_BREAKER_RESET_SECONDS = 30
"""
PR_FILE = """---
title: "fix(risk): restore cache TTL and bound the fraud-model call"
branch: incident/INC-4412-cache-ttl
base: main
---
## Summary

Restores `CACHE_TTL_SECONDS` to 300, bounds the fraud-model call and adds backoff.

## Postmortem draft

Blameless. The change was reviewed as a tuning knob because it looked like one.
"""


MODEL_PR_FILE = """---
title: "chore(ml): point-in-time features and the four validation gates"
branch: ml/TESS-2310-point-in-time-features
base: main
---
## Summary

`card_chargeback_rate` was computed with a `groupby` over the whole frame, and
`chargeback_filed_at` is ~85% of the label. Point-in-time, the lift is −0.0008
AUC. TESS-2310 stays blocked.
"""
AGGREGATES = '''def card_chargeback_rate(df, as_of):
    """Chargebacks filed strictly before each transaction. Nothing from the future."""
    return df
'''


def git(*args: str) -> None:
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@tessera.test", *args],
                   check=True, capture_output=True)


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv:
        print("0.0.0-fake (Claude Code)")
        return
    session = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "fake-session"
    delay = float(os.environ.get("FAKE_CLAUDE_DELAY", "0.005"))
    fail = os.environ.get("TESSERA_FAKE_FAIL")
    make_pr = os.environ.get("TESSERA_FAKE_MAKE_PR") == "1"

    if fail == "auth":
        print("Not logged in. Please run /login", file=sys.stderr)
        sys.exit(1)
    if fail == "hang":
        time.sleep(60)
        sys.exit(0)

    prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
    model_track = "validate-model" in prompt or "fraud-v3" in prompt or "shadow report" in prompt
    fixture = MODEL_FIXTURE if model_track else FIXTURE

    lines = fixture.read_text().replace("__SESSION__", session).splitlines()
    for index, line in enumerate(lines):
        if fail == "exit" and index == 3:
            print("boom: simulated crash", file=sys.stderr)
            sys.exit(2)
        if fail == "maxturns" and '"type":"result"' in line:
            line = line.replace('"subtype":"success","is_error":false', '"subtype":"error_max_turns","is_error":true')
        print(line, flush=True)
        if make_pr and model_track and '"toolu_m10"' in line and '"tool_use"' in line:
            git("checkout", "-q", "-b", MODEL_BRANCH)
            for path, body in (("ml/features/aggregates.py", AGGREGATES),
                               ("ml/validation/leakage.py", "# --fail-on-leak\n"),
                               ("ml/validation/tests/test_negative_fixture.py", "# the notebook's definition\n"),
                               ("ml/fraud/MODEL_CARD.md", "# fraud-v2 model card\n")):
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
            git("add", "-A")
            git("commit", "-q", "-m", "chore(ml): point-in-time features and the four validation gates")
        if make_pr and model_track and '"toolu_m11"' in line and '"tool_use"' in line:
            prs = Path(".tessera/prs")
            prs.mkdir(parents=True, exist_ok=True)
            (prs / "ml__TESS-2310-point-in-time-features.md").write_text(MODEL_PR_FILE)
        if make_pr and not model_track and '"toolu_09"' in line and '"tool_use"' in line:
            git("checkout", "-q", "-b", BRANCH)
            Path("services/risk_gateway/config.py").write_text(FIXED_CONFIG)
            git("add", "-A")
            git("commit", "-q", "-m", "fix(risk): restore cache ttl, bound timeout, back off retries")
        if make_pr and not model_track and '"toolu_10"' in line and '"tool_use"' in line:
            prs = Path(".tessera/prs")
            prs.mkdir(parents=True, exist_ok=True)
            (prs / "incident__INC-4412-cache-ttl.md").write_text(PR_FILE)
        time.sleep(delay)
    if fail == "maxturns":
        sys.exit(1)


if __name__ == "__main__":
    main()
