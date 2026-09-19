import pytest

from services.console.bus import EventBus
from services.console.timeline import Timeline


def test_append_persists_and_publishes(tmp_path):
    bus = EventBus()
    timeline = Timeline(tmp_path / ".tessera" / "events.jsonl", bus)
    event = timeline.append("alert_fired", "sre", "INC-4412 paged", refs={"incident_id": "INC-4412"})
    assert event["id"].startswith("evt_") and event["persona"] == "sre"
    assert timeline.load() == [event]
    assert bus.history("timeline")[0]["id"] == event["id"]
    timeline.append("triage_started", "claude", "Headless triage started")
    assert [e["type"] for e in timeline.load()] == ["alert_fired", "triage_started"]
    timeline.clear()
    assert timeline.load() == []


def test_rejects_unknown_type_or_persona(tmp_path):
    timeline = Timeline(tmp_path / "events.jsonl", EventBus())
    with pytest.raises(ValueError):
        timeline.append("coffee_break", "sre", "x")
    with pytest.raises(ValueError):
        timeline.append("alert_fired", "cto", "x")
