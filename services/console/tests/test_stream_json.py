import json
from pathlib import Path

from services.console.stream_json import PHASES, StreamParser, classify, summarize

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stream_json_sample.jsonl"


def parse_all(run_id="run_x"):
    parser = StreamParser(run_id)
    events = []
    for line in FIXTURE.read_text().replace("__SESSION__", "sess-1").splitlines():
        events.extend(parser.parse(line))
    return parser, events


def test_fixture_yields_the_expected_event_sequence():
    parser, events = parse_all()
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session" and parser.session_id == "sess-1"
    assert kinds[-1] == "result"
    assert kinds.count("tool_call") == 11
    assert kinds.count("tool_result") == 11
    assert "thinking" in kinds and "permission_denied" in kinds
    assert "hook" in kinds and "text" in kinds
    assert all(e["run_id"] == "run_x" for e in events)


def test_phases_are_emitted_once_in_triage_order():
    parser, events = parse_all()
    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["evidence", "correlate", "prove", "fix", "test", "pr"]
    assert [PHASES.index(p) for p in phases] == sorted(PHASES.index(p) for p in phases)
    assert parser.phases_seen == phases


def test_subagent_tool_calls_are_attributed_to_the_task_agent():
    _, events = parse_all()
    metrics_read = next(e for e in events if e["type"] == "tool_call" and "metrics.csv" in e["summary"])
    assert metrics_read["agent"] == "incident-responder"
    assert metrics_read["parent_tool_use_id"] == "toolu_02"
    top_level = next(e for e in events if e["type"] == "tool_call" and e["tool"] == "Edit")
    assert top_level["agent"] == "main" and "parent_tool_use_id" not in top_level


def test_tool_results_carry_tool_name_and_preview():
    _, events = parse_all()
    result = next(e for e in events if e["type"] == "tool_result" and e["tool_use_id"] == "toolu_03")
    assert result["tool"] == "Read" and result["preview"].startswith("timestamp,fraud_model_rps")
    task_result = next(e for e in events if e["type"] == "tool_result" and e["tool_use_id"] == "toolu_02")
    assert task_result["tool"] == "Task" and "d04bd8a" in task_result["preview"]


def test_hook_lines_become_hook_events_with_a_decision():
    _, events = parse_all()
    started, response = [e for e in events if e["type"] == "hook"]
    assert started["subtype"] == "hook_started" and started["decision"] is None
    assert response["hook_event_name"] == "PreToolUse" and response["tool_name"] == "Read"
    assert response["decision"] == "allow" and response["exit_code"] == 0 and response["outcome"] == "success"


def test_permission_denied_and_noise_lines():
    _, events = parse_all()
    [denied] = [e for e in events if e["type"] == "permission_denied"]
    assert denied["tool_name"] == "Skill" and "no approval surface" in denied["reason"]
    skill = next(e for e in events if e["type"] == "tool_call" and e["tool"] == "Skill")
    assert skill["summary"] == "/triage-incident INC-4412"
    [thinking] = [e for e in events if e["type"] == "thinking"]
    assert thinking["tokens"] == 50
    [rate] = [e for e in events if e["type"] == "raw"]
    assert rate["message_type"] == "rate_limit_event"


def test_result_event_fields():
    _, events = parse_all()
    result = events[-1]
    assert result["num_turns"] == 23 and result["cost_usd"] == 4.21 and result["is_error"] is False
    assert result["subtype"] == "success" and "ready for review" in result["result_text"]


def test_malformed_and_unknown_lines_become_raw_events():
    parser = StreamParser("r")
    assert parser.parse("") == []
    [bad] = parser.parse("this is not json")
    assert bad["type"] == "raw" and bad["note"] == "not json"
    [odd] = parser.parse(json.dumps({"type": "stream_event", "event": {"x": 1}}))
    assert odd["type"] == "raw" and odd["message_type"] == "stream_event"
    [sys_] = parser.parse(json.dumps({"type": "system", "subtype": "compact_boundary"}))
    assert sys_["type"] == "system" and sys_["subtype"] == "compact_boundary"


def test_agent_tool_is_attributed_like_task():
    parser = StreamParser("r")
    parser.parse(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "ag1", "name": "Agent", "input": {"subagent_type": "incident-responder", "description": "Triage"}}]}}))
    [nested] = parser.parse(json.dumps({"type": "assistant", "parent_tool_use_id": "ag1", "message": {"content": [
        {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/x/CLAUDE.md"}}]}}))
    assert nested["agent"] == "incident-responder"
    assert summarize("Agent", {"subagent_type": "model-validator", "description": "check"}) == "model-validator: check"


def test_summaries_and_classification():
    assert summarize("Edit", {"file_path": "a.py", "old_string": "ab", "new_string": "abcd"}) == "a.py (−2 +4 chars)"
    assert summarize("Bash", {"command": "x" * 200}).endswith("…")
    assert summarize("Task", {"subagent_type": "model-validator", "description": "check leakage"}) == "model-validator: check leakage"
    assert classify("Bash", {"command": "git show d04bd8a"}) == "correlate"
    assert classify("Bash", {"command": "uv run python -m services.risk_gateway.simulation --json"}) == "prove"
    assert classify("Edit", {"file_path": "/x/ops/runbooks/risk-gateway.md"}) == "runbook"
    assert classify("Write", {"file_path": "/x/ml/features/tests/test_aggregates.py"}) == "test"
    assert classify("Read", {"file_path": "/x/CLAUDE.md"}) is None


def test_long_inputs_are_truncated_but_kept():
    parser = StreamParser("r")
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t", "name": "Write", "input": {"file_path": "big.py", "content": "z" * 5000}}]}})
    [call] = parser.parse(line)
    assert call["input"]["content"].endswith("[5000 chars]") and len(call["input"]["content"]) < 2100
