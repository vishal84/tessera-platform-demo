"""
In-process event bus behind the console's single SSE stream.

Every event gets a monotonically increasing `seq`, and the last few thousand
are kept in a ring buffer so a reconnecting browser can resume from
`Last-Event-ID` instead of refetching the world. All producers run on the
asyncio loop; nothing here is thread-safe by design.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

CHANNELS = ("run", "activity", "audit", "timeline", "gate", "health", "pr")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Event:
    seq: int
    channel: str
    data: dict

    def sse(self) -> str:
        return f"id: {self.seq}\nevent: {self.channel}\ndata: {json.dumps(self.data)}\n\n"


class EventBus:
    def __init__(self, buffer_size: int = 2000) -> None:
        self._seq = 0
        self._buffer: deque[Event] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @property
    def last_seq(self) -> int:
        return self._seq

    def publish(self, channel: str, payload: dict) -> Event:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        self._seq += 1
        data = {**payload, "seq": self._seq}
        data.setdefault("ts", now_iso())
        event = Event(self._seq, channel, data)
        self._buffer.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    def since(self, seq: int) -> list[Event]:
        return [event for event in self._buffer if event.seq > seq]

    def history(self, channel: str, limit: int = 200) -> list[dict]:
        events = [event.data for event in self._buffer if event.channel == channel]
        return events[-limit:]
