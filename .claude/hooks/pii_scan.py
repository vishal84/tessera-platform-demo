#!/usr/bin/env python3
"""
Tessera Financial -- cardholder data scanner (PostToolUse hook).

Runs after every file write. Catches the two mistakes that turn a routine PR
into a PCI-DSS reportable event:

  1. Cardholder data hardcoded into source or tests (PAN, CVV, SSN).
  2. Logging a sensitive field -- the classic "just add a debug line" that
     ships a PAN to the log aggregator, where it is retained for 90 days
     across three vendors and is now in scope for the whole audit.

Exit 2 tells the agent what it just wrote and asks it to fix it. The write has
already landed; this is a fast feedback loop, not a lock. The hard lock for
secret material is protect_secrets.py, which runs *before* the write.

Every scan appends a line to .tessera/audit.jsonl (allow or warn), the same
trail protect_secrets.py writes, so the ops console can show both hooks.

Run `python3 pii_scan.py --selftest` to verify.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE_FIELDS = (
    r"card_number|cardnumber|\bpan\b|\bcvv\b|\bcvc\b|card_verification|"
    r"\bssn\b|social_security|tax_id|\bcvn\b|track_data|full_track|"
    r"account_number|routing_number|card_expiry|expiry_date"
)

LOG_CALL = re.compile(
    rf"(?:log(?:ger|ging)?|print|console\.\w+)\s*(?:\.\w+\s*)?\([^)\n]*(?:{SENSITIVE_FIELDS})",
    re.IGNORECASE,
)

SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
DIGIT_RUN = re.compile(r"(?<![\d.])\d[\d \-]{11,21}\d(?![\d.])")

SCANNABLE = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".ipynb",
             ".yaml", ".yml", ".json", ".sql", ".sh", ".md"}

# Files that are allowed to contain test PANs (they are published test numbers).
EXEMPT = re.compile(r"(?:test_fixtures|/fixtures/|\.claude/hooks/|docs/pci)")


AUDIT_RELPATH = Path(".tessera") / "audit.jsonl"


def audit(event: dict | None, decision: str, target: str, reason: str | None = None) -> None:
    """
    Append one JSON line to <project>/.tessera/audit.jsonl. Best-effort: a
    logging failure must never change the exit code. Mirrors the function of
    the same name in protect_secrets.py; the two hooks stay dependency-free
    and independently readable, so the duplication is deliberate.
    """
    if not event or os.environ.get("TESSERA_AUDIT_DISABLE"):
        return
    try:
        root = (
            os.environ.get("TESSERA_AUDIT_DIR")
            or os.environ.get("CLAUDE_PROJECT_DIR")
            or event.get("cwd")
            or os.getcwd()
        )
        path = Path(root) / AUDIT_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "hook": "pii_scan",
            "event": event.get("hook_event_name"),
            "session_id": event.get("session_id"),
            "agent_type": event.get("agent_type"),
            "agent_id": event.get("agent_id"),
            "permission_mode": event.get("permission_mode"),
            "tool_name": event.get("tool_name"),
            "target": str(target)[:200],
            "decision": decision,
            "reason": reason,
            "cwd": event.get("cwd"),
            "pid": os.getpid(),
        }
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 -- logging must never change the exit code
        pass


def luhn_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str, path: str = "") -> list[str]:
    findings: list[str] = []
    if EXEMPT.search(path):
        return findings

    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*")):
            continue

        if LOG_CALL.search(line):
            findings.append(
                f"line {i}: logs a cardholder-data field -- this would emit "
                f"CHD to the log pipeline\n           {stripped[:100]}"
            )

        if SSN.search(line):
            findings.append(f"line {i}: SSN-shaped literal in source\n           {stripped[:100]}")

        for candidate in DIGIT_RUN.findall(line):
            digits = re.sub(r"[ \-]", "", candidate)
            if luhn_valid(digits):
                findings.append(
                    f"line {i}: Luhn-valid card number literal "
                    f"({digits[:4]}...{digits[-4:]})\n           {stripped[:100]}"
                )
    return findings


CASES = [
    ('logger.info("charging card %s", card_number)', True),
    ('print(f"cvv={cvv}")', True),
    ('pan = "4111111111111111"', True),
    ('ssn = "123-45-6789"', True),
    ('logger.info("charging card %s", card_token)', False),
    ('amount_minor = 4111111111111112', False),   # not Luhn-valid
    ('# logger.info("card %s", card_number)', False),  # commented out
    ('order_id = 1234567890123', False),
]


def selftest() -> int:
    failures = 0
    for snippet, should_flag in CASES:
        flagged = bool(scan(snippet))
        ok = flagged == should_flag
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {'FLAG ' if flagged else 'clean':<5}  {snippet}")
    print()
    print(f"{failures} selftest case(s) failed" if failures
          else f"all {len(CASES)} selftest cases passed")
    return 1 if failures else 0


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    path = (event.get("tool_input", {}) or {}).get("file_path", "")
    if not path or Path(path).suffix not in SCANNABLE:
        sys.exit(0)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        sys.exit(0)

    findings = scan(text, path)
    audit(event, "warn" if findings else "allow", path,
          reason=findings[0].splitlines()[0] if findings else None)
    if findings:
        joined = "\n  - ".join(findings)
        print(
            f"CARDHOLDER DATA WARNING in {path}\n\n  - {joined}\n\n"
            f"Tessera is PCI-DSS Level 1. Cardholder data must never appear in "
            f"source, tests, or logs.\nUse a token (tok_*) or the fixtures in "
            f"tests/fixtures/. Fix this before committing.",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
