"""Live runs against the fake claude: streaming, recording, detection, failure modes."""

import time

import pytest


def wait_until(predicate, timeout: float = 15.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def finished(client, run_id):
    return wait_until(lambda: (m := client.get(f"/api/runs/{run_id}").json()) if
                      client.get(f"/api/runs/{run_id}").json()["status"] not in ("running", "cancelling") else None)


def test_live_run_streams_records_and_detects_the_pr(live_client, settings, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")
    started = live_client.post("/api/runs", json={"incident_id": "INC-4412"})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["mode"] == "live" and run["session_id"] and run["status"] == "running"
    assert "--include-hook-events" in run["argv"] and "--permission-prompts" in run["argv"]
    assert "--append-system-prompt" in run["argv"], "local mode adds the PR contract"
    allowed = run["argv"][run["argv"].index("--allowedTools") + 1]
    assert "gh pr create" not in allowed and "Bash(git:*)" in allowed
    assert run["argv"][2].startswith("Run /triage-incident INC-4412")

    final = finished(live_client, run["run_id"])
    assert final["status"] == "finished", final
    assert final["branch"] == "incident/INC-4412-cache-ttl"
    assert final["pr_id"] == "incident/INC-4412-cache-ttl"
    assert final["num_turns"] == 23 and final["cost_usd"] == 4.21 and final["error"] is None

    events = live_client.get(f"/api/runs/{run['run_id']}/events").json()
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session" and kinds[-1] == "result"
    assert [e["phase"] for e in events if e["type"] == "phase"] == ["evidence", "correlate", "prove", "fix", "test", "pr"]
    assert all(e["replayed"] is False for e in events)
    after = events[5]["seq"]
    assert live_client.get(f"/api/runs/{run['run_id']}/events?after={after}").json()[0]["seq"] == events[6]["seq"]

    run_dir = settings.runs_dir / run["run_id"]
    assert (run_dir / "run.jsonl").is_file() and (run_dir / "meta.json").is_file()
    assert (run_dir / "pr.md").is_file() and (run_dir / "branch.patch").is_file()
    assert "fix(risk): restore cache ttl" in (run_dir / "branch.patch").read_text()
    assert len((run_dir / "run.jsonl").read_text().splitlines()) == 31

    [pr] = live_client.get("/api/prs").json()
    assert pr["id"] == "incident/INC-4412-cache-ttl" and pr["state"] == "open"
    assert pr["incident_id"] == "INC-4412" and len(pr["commits"]) == 1
    assert [f["path"] for f in pr["files"]] == ["services/risk_gateway/config.py"]
    assert pr["title"].startswith("fix(risk)")

    types = [e["type"] for e in live_client.get("/api/timeline").json()]
    for expected in ("triage_started", "evidence_read", "hypothesis_proven", "pr_opened"):
        assert expected in types, types
    pr_event = next(e for e in live_client.get("/api/timeline").json() if e["type"] == "pr_opened")
    assert pr_event["refs"]["run_id"] == run["run_id"]

    [incident] = live_client.get("/api/incidents").json()
    assert incident["status"] == "pr_open"
    assert live_client.get("/api/health").json()["run"] == {"active": False, "run_id": None}
    assert live_client.get("/api/runs").json()[-1]["run_id"] == run["run_id"]


def test_second_run_is_rejected_while_one_is_active_and_cancel_works(live_client, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.15")
    first = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    second = live_client.post("/api/runs", json={"incident_id": "INC-4412"})
    assert second.status_code == 409
    assert second.json()["error"]["details"] == {"run_id": first["run_id"]}
    assert live_client.get("/api/health").json()["run"]["active"] is True

    cancelled = live_client.post(f"/api/runs/{first['run_id']}/cancel")
    assert cancelled.status_code == 200
    final = finished(live_client, first["run_id"])
    assert final["status"] == "cancelled"
    assert "run_cancelled" in [e["type"] for e in live_client.get("/api/timeline").json()]
    assert live_client.post(f"/api/runs/{first['run_id']}/cancel").status_code == 409


def test_preflight_names_every_problem(live_client, demo_repo):
    (demo_repo / "README.md").write_text("edited\n")
    response = live_client.post("/api/runs", json={"incident_id": "INC-4412"})
    assert response.status_code == 412
    details = response.json()["error"]["details"]
    assert any("uncommitted" in d for d in details)
    missing = live_client.post("/api/runs", json={"incident_id": "INC-0000"})
    assert missing.status_code == 412 and any("no evidence bundle" in d for d in missing.json()["error"]["details"])


def test_auth_failure_is_classified(live_client, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_FAIL", "auth")
    run = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    final = finished(live_client, run["run_id"])
    assert final["status"] == "failed"
    assert final["error"]["kind"] == "auth" and "Not logged in" in final["error"]["stderr_tail"]
    assert "run_failed" in [e["type"] for e in live_client.get("/api/timeline").json()]


def test_crash_mid_stream_keeps_what_was_streamed(live_client, settings, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_FAIL", "exit")
    run = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    final = finished(live_client, run["run_id"])
    assert final["status"] == "failed" and final["error"]["kind"] == "exit"
    assert "boom" in final["error"]["stderr_tail"]
    events = live_client.get(f"/api/runs/{run['run_id']}/events").json()
    assert len(events) >= 3 and events[0]["type"] == "session"
    assert len((settings.runs_dir / run["run_id"] / "run.jsonl").read_text().splitlines()) == 3


def test_run_contract_is_read_from_the_workflow_file(client):
    contract = client.get("/api/runs/contract").json()
    assert contract["source"] == ".github/workflows/claude-incident-fix.yml"
    assert contract["prompt"].startswith("Run /triage-incident {incident_id}")
    assert "Bash(uv run:*)" in contract["allowed_tools"] and contract["max_turns"] == 60
    assert contract["provider"] == "local"
    assert "--allowedTools" in contract["argv"]
    allowed = contract["argv"][contract["argv"].index("--allowedTools") + 1]
    assert "gh pr create" not in allowed and "Task" in allowed
    assert client.get("/api/runs/nope").status_code == 404


def test_max_turns_with_a_pr_is_finished_with_a_warning(live_client, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")
    monkeypatch.setenv("TESSERA_FAKE_FAIL", "maxturns")
    run = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    final = finished(live_client, run["run_id"])
    assert final["status"] == "finished", final
    assert final["pr_id"] == "incident/INC-4412-cache-ttl" and final["error"] is None
    assert final["warning"].startswith("exit:")
    assert "run_failed" not in [e["type"] for e in live_client.get("/api/timeline").json()]


def test_max_turns_without_a_pr_is_a_failure(live_client, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_FAIL", "maxturns")
    run = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    final = finished(live_client, run["run_id"])
    assert final["status"] == "failed" and final["error"]["kind"] == "exit"
