"""
Tails the guardrail audit trail the hooks write and turns it into UI events.

Only lines appended after the console started are streamed and promoted to
timeline events; history is served by `query()`. That keeps a restart from
replaying every old deny as a fresh "guardrail blocked" moment.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path

from .bus import EventBus
from .timeline import Timeline

SourceResolver = Callable[[str | None], tuple[str, str | None]]


def tag(record: dict, resolve: SourceResolver) -> dict:
    source, run_id = resolve(record.get("session_id"))
    return {**record, "source": source, "run_id": run_id}


class AuditTailer:
    def __init__(self, path: Path, bus: EventBus, timeline: Timeline, resolve: SourceResolver,
                 persona_for_desktop: Callable[[], str], interval: float = 0.5,
                 dedupe_seconds: float = 5.0) -> None:
        self.path, self.bus, self.timeline = path, bus, timeline
        self.resolve, self.persona_for_desktop = resolve, persona_for_desktop
        self.interval, self.dedupe_seconds = interval, dedupe_seconds
        self._offset = 0
        self._last_block: tuple[str, float] | None = None

    # --- history ------------------------------------------------------------
    def query(self, since: str | None = None, decisions: set[str] | None = None,
              limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
            record = _parse(line)
            if record is None:
                continue
            if since and record.get("ts", "") <= since:
                continue
            if decisions and record.get("decision") not in decisions:
                continue
            records.append(tag(record, self.resolve))
        return records[-limit:]

    # --- live ---------------------------------------------------------------
    def start_at_end(self) -> None:
        self._offset = self.path.stat().st_size if self.path.exists() else 0

    def poll(self) -> list[dict]:
        """Read whatever was appended since the last poll. Returns the new records."""
        if not self.path.exists():
            self._offset = 0
            return []
        size = self.path.stat().st_size
        if size < self._offset:      # truncated (reset-demo.sh) -- start over
            self._offset = 0
        if size == self._offset:
            return []
        with self.path.open("rb") as fh:
            fh.seek(self._offset)
            chunk = fh.read(size - self._offset)
        # Never consume a partial trailing line; the hook may still be writing it.
        cut = chunk.rfind(b"\n")
        if cut == -1:
            return []
        self._offset += cut + 1
        records = []
        for raw in chunk[:cut].split(b"\n"):
            record = _parse(raw.decode("utf-8", errors="ignore"))
            if record is not None:
                records.append(self._emit(record))
        return records

    def _emit(self, record: dict) -> dict:
        tagged = tag(record, self.resolve)
        self.bus.publish("audit", tagged)
        if tagged.get("decision") == "deny":
            self._promote(tagged)
        return tagged

    def _promote(self, record: dict) -> None:
        key = f"{record.get('tool_name')}:{record.get('target')}"
        stamp = time.monotonic()
        if self._last_block and self._last_block[0] == key and stamp - self._last_block[1] < self.dedupe_seconds:
            return
        self._last_block = (key, stamp)
        persona = "claude" if record["source"] == "run" else self.persona_for_desktop()
        where = "headless run" if record["source"] == "run" else "desktop session"
        self.timeline.append(
            "guardrail_blocked", persona,
            f"Guardrail blocked {record.get('tool_name')} on {record.get('target')}",
            detail=f"protect_secrets denied it in the {where} (matched {record.get('reason')!r})",
            refs={"run_id": record.get("run_id"), "path": record.get("target")},
        )

    async def run(self) -> None:
        self.start_at_end()
        while True:
            try:
                await asyncio.to_thread(self.poll)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self.interval)


def _parse(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None

