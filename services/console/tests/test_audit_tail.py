import json

from services.console.audit import AuditTailer
from services.console.bus import EventBus
from services.console.timeline import Timeline


def line(**overrides) -> str:
    record = {"ts": "2026-09-20T10:00:00.000+00:00", "hook": "protect_secrets", "event": "PreToolUse",
              "session_id": "desk-1", "tool_name": "Write", "target": ".env", "decision": "deny",
              "reason": ".env", "cwd": "/repo", "pid": 1}
    return json.dumps({**record, **overrides}) + "\n"


def make(tmp_path, resolve=None, persona="swe"):
    bus = EventBus()
    timeline = Timeline(tmp_path / "events.jsonl", bus)
    path = tmp_path / "audit.jsonl"
    resolve = resolve or (lambda sid: ("run", "run_1") if sid == "run-sess" else ("desktop", None))
    return path, bus, timeline, AuditTailer(path, bus, timeline, resolve, lambda: persona, dedupe_seconds=0.0)


def test_only_lines_after_start_are_streamed_and_denies_reach_the_timeline(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    path.write_text(line() + line(decision="allow", target="README.md"))
    tailer.start_at_end()
    assert tailer.poll() == []

    with path.open("a") as fh:
        fh.write(line(target="secrets/prod.yaml", reason="secrets/") + line(decision="allow", target="docs/config.md"))
    records = tailer.poll()
    assert [r["decision"] for r in records] == ["deny", "allow"]
    assert records[0]["source"] == "desktop" and records[0]["run_id"] is None
    assert [e["seq"] for e in bus.history("audit")] == [1, 3]
    [blocked] = [e for e in timeline.load() if e["type"] == "guardrail_blocked"]
    assert blocked["persona"] == "swe" and "secrets/prod.yaml" in blocked["title"]


def test_run_sessions_are_attributed_to_claude(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    tailer.start_at_end()
    path.write_text(line(session_id="run-sess"))
    [record] = tailer.poll()
    assert record["source"] == "run" and record["run_id"] == "run_1"
    assert timeline.load()[0]["persona"] == "claude"


def test_truncation_restarts_from_the_top(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    path.write_text(line() * 5)
    tailer.start_at_end()
    path.write_text(line(decision="allow", target="a.py"))          # shorter than before
    assert [r["target"] for r in tailer.poll()] == ["a.py"]


def test_partial_trailing_line_is_left_for_the_next_poll(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    tailer.start_at_end()
    full = line(decision="allow", target="x.py")
    path.write_bytes(full[:-10].encode())
    assert tailer.poll() == []
    with path.open("ab") as fh:
        fh.write(full[-10:].encode())
    assert len(tailer.poll()) == 1


def test_dedupe_suppresses_a_repeated_block_within_the_window(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    tailer.dedupe_seconds = 60.0
    tailer.start_at_end()
    path.write_text(line() + line() + line(target=".env.production"))
    tailer.poll()
    assert [e["title"] for e in timeline.load()] == [
        "Guardrail blocked Write on .env", "Guardrail blocked Write on .env.production"]


def test_query_filters_and_tags(tmp_path):
    path, bus, timeline, tailer = make(tmp_path)
    path.write_text(line() + line(decision="allow", target="a.py", ts="2026-09-20T10:00:01.000+00:00")
                    + line(decision="warn", hook="pii_scan", target="b.py", ts="2026-09-20T10:00:02.000+00:00"))
    assert [r["decision"] for r in tailer.query()] == ["deny", "allow", "warn"]
    assert [r["decision"] for r in tailer.query(decisions={"deny", "warn"})] == ["deny", "warn"]
    assert [r["target"] for r in tailer.query(since="2026-09-20T10:00:00.000+00:00")] == ["a.py", "b.py"]
    assert len(tailer.query(limit=1)) == 1
    assert tailer.query()[0]["source"] == "desktop"
