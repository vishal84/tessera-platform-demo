"""The policy panel: what the guardrails are, straight from the files that define them."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

import yaml

from .settings import Settings

_SELFTEST_CACHE: dict[str, tuple[float, dict]] = {}
_PASSED = re.compile(r"all (\d+) selftest cases passed")
_FAILED = re.compile(r"(\d+) selftest case\(s\) failed")


def selftest(settings: Settings, hook: str, ttl: float = 60.0) -> dict:
    key = str(settings.hooks_dir / hook)
    cached = _SELFTEST_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]
    proc = subprocess.run([sys.executable, key, "--selftest"], capture_output=True, text=True,
                          env={**os.environ, "TESSERA_AUDIT_DISABLE": "1"})
    passed = _PASSED.search(proc.stdout)
    failed = _FAILED.search(proc.stdout)
    total = int(passed.group(1)) if passed else None
    failures = int(failed.group(1)) if failed else 0
    result = {"passed": (total or 0) - failures if total is not None else None,
              "failed": failures, "exit_code": proc.returncode}
    _SELFTEST_CACHE[key] = (time.monotonic(), result)
    return result


def policy(settings: Settings) -> dict:
    claude = json.loads(settings.claude_settings.read_text()) if settings.claude_settings.exists() else {}
    permissions = claude.get("permissions", {})
    hooks = []
    for event, groups in (claude.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                hooks.append({"event": event, "matcher": group.get("matcher"), "command": hook.get("command")})
    return {
        "deny": permissions.get("deny", []),
        "allow": permissions.get("allow", []),
        "hooks": hooks,
        "selftests": {
            "protect_secrets": selftest(settings, "protect_secrets.py"),
            "pii_scan": selftest(settings, "pii_scan.py"),
        },
        "ci_mirror": ci_mirror(settings),
    }


def ci_mirror(settings: Settings) -> list[dict]:
    """The steps in ci.yml and claude-incident-fix.yml that re-run the same guardrails."""
    steps = []
    for name in ("ci.yml", "claude-incident-fix.yml"):
        path = settings.workflows_dir / name
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text()) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps", []):
                run = step.get("run")
                if run and (".claude/hooks" in run or "protect_secrets" in run or "pii_scan" in run):
                    steps.append({"workflow": name, "job": job_name, "step": step.get("name"),
                                  "command": run.strip().splitlines()[0]})
    return steps
