import json


def test_health_reports_repo_and_environment(client, settings):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["repo"]["branch"] == "main" and body["repo"]["clean"] is True
    assert body["provider"] == "local"
    assert body["run"] == {"active": False, "run_id": None}
    assert body["persona"] == "sre"


def test_gateway_health_is_degraded_on_the_seeded_config(client):
    body = client.get("/api/gateway/health").json()
    assert body["production"]["verdict"] == "degraded"
    assert body["production"]["ref"] == "main"
    assert body["working_tree"]["branch"] == "main"
    assert body["slo"] == {"success_rate": 0.995, "p99_seconds": 1.0}


def test_incidents_list_and_detail(client):
    [inc] = client.get("/api/incidents").json()
    assert inc["id"] == "INC-4412" and inc["status"] == "open"
    detail = client.get("/api/incidents/INC-4412").json()
    assert len(detail["metrics"]) == 71 and detail["status"] == "open"
    missing = client.get("/api/incidents/INC-0000")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "no evidence bundle for INC-0000"}}


def test_timeline_roundtrip_and_persona_tracking(client):
    created = client.post("/api/timeline", json={"type": "alert_fired", "persona": "sre",
                                                 "title": "INC-4412 paged", "refs": {"incident_id": "INC-4412"}})
    assert created.status_code == 201
    assert client.get("/api/timeline").json()[0]["id"] == created.json()["id"]

    bad = client.post("/api/timeline", json={"type": "alert_fired", "persona": "cto", "title": "x"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_event"

    client.post("/api/timeline", json={"type": "review_requested", "persona": "swe", "title": "Review please"})
    assert client.get("/api/health").json()["persona"] == "swe"
    assert client.post("/api/persona", json={"persona": "ds"}).json() == {"persona": "ds"}
    assert client.post("/api/persona", json={"persona": "cto"}).status_code == 400


def test_guardrails_policy_reflects_the_files(client):
    body = client.get("/api/guardrails/policy").json()
    assert "Read(./.env)" in body["deny"]
    assert {h["event"] for h in body["hooks"]} == {"PreToolUse", "PostToolUse"}
    assert body["selftests"]["protect_secrets"] == {"passed": 22, "failed": 0, "exit_code": 0}
    assert body["selftests"]["pii_scan"]["failed"] == 0
    assert any(s["workflow"] == "ci.yml" and "protect_secrets" in s["command"] for s in body["ci_mirror"])
    assert any(s["workflow"] == "claude-incident-fix.yml" for s in body["ci_mirror"])


def test_guardrails_audit_serves_history_tagged_by_source(client, settings):
    assert client.get("/api/guardrails/audit").json() == []
    settings.audit_path.parent.mkdir(parents=True, exist_ok=True)
    settings.audit_path.write_text(json.dumps({"ts": "2026-09-20T10:00:00.000+00:00", "hook": "protect_secrets",
                                               "session_id": "abc", "tool_name": "Write", "target": ".env",
                                               "decision": "deny"}) + "\n")
    [record] = client.get("/api/guardrails/audit?decision=deny,warn").json()
    assert record["source"] == "desktop"
    assert client.get("/api/guardrails/audit?decision=allow").json() == []


def test_unknown_api_paths_are_json_404s_and_spa_placeholder_when_unbuilt(client):
    missing = client.get("/api/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    root = client.get("/")
    assert root.status_code == 503 and "npm --prefix web" in root.text


def test_live_client_runs_the_pollers(live_client, settings):
    import time
    settings.audit_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.audit_path.open("a") as fh:
        fh.write(json.dumps({"ts": "2026-09-20T10:00:00.000+00:00", "hook": "protect_secrets", "session_id": "d",
                             "tool_name": "Bash", "target": "cat .env", "decision": "deny", "reason": ".env"}) + "\n")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        events = live_client.get("/api/timeline").json()
        if any(e["type"] == "guardrail_blocked" for e in events):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("audit tailer never promoted the deny")
