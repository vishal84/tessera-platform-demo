"""
The two guardrail hooks append one audit line per decision, and logging can
never change their exit code. The ops console reads this trail; these tests
pin its shape.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOKS = REPO / ".claude" / "hooks"

EVENT_BASE = {
    "session_id": "sess-test-0001",
    "hook_event_name": "PreToolUse",
    "cwd": str(REPO),
    "permission_mode": "acceptEdits",
    "agent_type": "incident-responder",
}


def run_hook(script: str, event: dict, audit_dir: Path, **env_overrides: str):
    env = {k: v for k, v in os.environ.items() if k != "TESSERA_AUDIT_DISABLE"}
    env["TESSERA_AUDIT_DIR"] = str(audit_dir)
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(event), capture_output=True, text=True, env=env,
    )
    log = audit_dir / ".tessera" / "audit.jsonl"
    lines = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return proc, lines


def test_secrets_deny_is_logged_and_still_exits_2(tmp_path):
    event = {**EVENT_BASE, "tool_name": "Write", "tool_input": {"file_path": ".env"}}
    proc, lines = run_hook("protect_secrets.py", event, tmp_path)
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr
    assert len(lines) == 1
    rec = lines[0]
    assert rec["hook"] == "protect_secrets"
    assert rec["decision"] == "deny"
    assert rec["tool_name"] == "Write"
    assert rec["target"] == ".env"
    assert rec["reason"] == ".env"
    assert rec["session_id"] == "sess-test-0001"
    assert rec["agent_type"] == "incident-responder"
    assert rec["ts"].endswith("+00:00")


def test_secrets_bash_deny_logs_the_command(tmp_path):
    event = {**EVENT_BASE, "tool_name": "Bash", "tool_input": {"command": "git add .env"}}
    proc, lines = run_hook("protect_secrets.py", event, tmp_path)
    assert proc.returncode == 2
    assert lines[0]["decision"] == "deny"
    assert lines[0]["target"] == "git add .env"


def test_secrets_allow_is_logged_and_exits_0(tmp_path):
    event = {**EVENT_BASE, "tool_name": "Edit",
             "tool_input": {"file_path": "services/payments_api/app.py"}}
    proc, lines = run_hook("protect_secrets.py", event, tmp_path)
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert len(lines) == 1
    assert lines[0]["decision"] == "allow"
    assert lines[0]["target"] == "services/payments_api/app.py"
    assert lines[0]["reason"] is None


def test_pii_warn_is_logged_and_still_exits_2(tmp_path):
    src = tmp_path / "charge.py"
    src.write_text('pan = "4111111111111111"\n')
    event = {**EVENT_BASE, "hook_event_name": "PostToolUse", "tool_name": "Write",
             "tool_input": {"file_path": str(src)}}
    proc, lines = run_hook("pii_scan.py", event, tmp_path)
    assert proc.returncode == 2
    assert "CARDHOLDER DATA WARNING" in proc.stderr
    assert len(lines) == 1
    assert lines[0]["hook"] == "pii_scan"
    assert lines[0]["decision"] == "warn"
    assert "Luhn-valid" in lines[0]["reason"]


def test_pii_clean_file_is_logged_as_allow(tmp_path):
    src = tmp_path / "clean.py"
    src.write_text('logger.info("charging card %s", card_token)\n')
    event = {**EVENT_BASE, "hook_event_name": "PostToolUse", "tool_name": "Write",
             "tool_input": {"file_path": str(src)}}
    proc, lines = run_hook("pii_scan.py", event, tmp_path)
    assert proc.returncode == 0
    assert lines[0]["decision"] == "allow"


def test_disable_env_suppresses_logging_but_not_the_verdict(tmp_path):
    event = {**EVENT_BASE, "tool_name": "Write", "tool_input": {"file_path": ".env"}}
    proc, lines = run_hook("protect_secrets.py", event, tmp_path, TESSERA_AUDIT_DISABLE="1")
    assert proc.returncode == 2
    assert lines == []


def test_unwritable_audit_dir_cannot_change_the_exit_code(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")  # .tessera/ cannot be created underneath a file
    deny = {**EVENT_BASE, "tool_name": "Write", "tool_input": {"file_path": ".env"}}
    allow = {**EVENT_BASE, "tool_name": "Write", "tool_input": {"file_path": "README.md"}}
    assert run_hook("protect_secrets.py", deny, blocker)[0].returncode == 2
    assert run_hook("protect_secrets.py", allow, blocker)[0].returncode == 0


def test_lines_append_across_invocations(tmp_path):
    for path in (".env", "docs/config.md", "secrets/prod.yaml"):
        event = {**EVENT_BASE, "tool_name": "Write", "tool_input": {"file_path": path}}
        run_hook("protect_secrets.py", event, tmp_path)
    _, lines = run_hook("protect_secrets.py",
                        {**EVENT_BASE, "tool_name": "Read", "tool_input": {"file_path": "CLAUDE.md"}},
                        tmp_path)
    assert [l["decision"] for l in lines] == ["deny", "allow", "deny", "allow"]
