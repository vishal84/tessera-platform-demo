import asyncio

import pytest

from services.console.bus import EventBus
from services.console.sse import stream


def test_publish_assigns_sequence_and_buffers_last_n():
    bus = EventBus(buffer_size=3)
    for i in range(4):
        bus.publish("timeline", {"i": i})
    assert bus.last_seq == 4
    assert [e.seq for e in bus.since(0)] == [2, 3, 4]
    assert [e.seq for e in bus.since(3)] == [4]
    latest = bus.history("timeline", limit=1)[0]
    assert latest["i"] == 3 and latest["seq"] == 4 and latest["ts"].endswith("+00:00")


def test_unknown_channel_is_rejected():
    with pytest.raises(ValueError):
        EventBus().publish("nope", {})


def test_sse_wire_format():
    event = EventBus().publish("audit", {"decision": "deny"})
    text = event.sse()
    assert text.startswith("id: 1\nevent: audit\ndata: {")
    assert text.endswith("}\n\n")


@pytest.mark.asyncio
async def test_stream_replays_from_last_event_id_then_goes_live_and_pings():
    bus = EventBus()
    bus.publish("run", {"n": 1})
    bus.publish("run", {"n": 2})
    gen = stream(bus, last_event_id=1, ping_interval=0.05)
    assert await anext(gen) == ": connected\n\n"
    assert "id: 2\n" in await anext(gen)
    bus.publish("run", {"n": 3})
    assert "id: 3\n" in await anext(gen)
    assert await anext(gen) == ": ping\n\n"
    await gen.aclose()
    assert not bus._subscribers, "subscription must be released on close"
