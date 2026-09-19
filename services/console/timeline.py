"""
The incident timeline: who did what, in order, across personas.

Persisted as JSONL under .tessera/ so a page reload (or a console restart
mid-demo) does not lose the story. The rail the UI draws is this file.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from .bus import EventBus, now_iso

PERSONAS = ("sre", "swe", "ds", "claude", "system")
TYPES = (
    "alert_fired", "triage_started", "evidence_read", "hypothesis_proven", "pr_opened",
    "review_requested", "guardrail_blocked", "pr_updated", "merged", "recovered",
    "shadow_report_opened", "notebook_opened", "notebook_updated", "gates_implemented",
    "gates_run", "gate_blocked", "gate_passed", "model_card_added", "run_failed",
    "run_replayed", "run_cancelled", "note",
    "investigation_started", "aggregates_added",
)


class Timeline:
    def __init__(self, path: Path, bus: EventBus) -> None:
        self.path, self.bus = path, bus

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def append(self, type: str, persona: str, title: str, detail: str | None = None,
               refs: dict | None = None) -> dict:
        if type not in TYPES:
            raise ValueError(f"unknown timeline type {type!r}")
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}")
        event = {
            "id": f"evt_{secrets.token_hex(4)}", "ts": now_iso(), "type": type,
            "persona": persona, "title": title, "detail": detail, "refs": refs or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        self.bus.publish("timeline", event)
        return event

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
