"""Server-sent events over Starlette's StreamingResponse. ~30 lines; no library."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import StreamingResponse

from .bus import EventBus


async def stream(bus: EventBus, last_event_id: int | None, ping_interval: float = 15.0) -> AsyncIterator[str]:
    queue = bus.subscribe()
    try:
        yield ": connected\n\n"
        if last_event_id is not None:
            for event in bus.since(last_event_id):
                yield event.sse()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_interval)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            yield event.sse()
    finally:
        bus.unsubscribe(queue)


def response(bus: EventBus, request: Request, ping_interval: float = 15.0) -> StreamingResponse:
    raw = request.headers.get("last-event-id") or request.query_params.get("after")
    last_event_id = int(raw) if raw and raw.isdigit() else None
    return StreamingResponse(
        stream(bus, last_event_id, ping_interval),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
