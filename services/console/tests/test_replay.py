import json
import shutil

from services.console.tests.conftest import git
from services.console.tests.test_runner import finished, wait_until


def test_replay_reproduces_the_stream_and_restores_the_branch_and_pr(live_client, settings, demo_repo, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")
    live = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    finished(live_client, live["run_id"])

    # Promote the run to the committed "golden" recording, then wipe its artifacts.
    golden = settings.recordings_dir / "triage-INC-4412"
    shutil.copytree(settings.runs_dir / live["run_id"], golden)
    git(demo_repo, "checkout", "-q", "main")
    git(demo_repo, "branch", "-D", "incident/INC-4412-cache-ttl")
    (settings.prs_dir / "incident__INC-4412-cache-ttl.md").unlink()
    assert live_client.get("/api/prs").json() == []
    assert live_client.get("/api/incidents").json()[0]["status"] == "pr_open", "timeline remembers the PR"

    listed = {r["name"]: r for r in live_client.get("/api/recordings").json()}
    assert listed["triage-INC-4412"]["source"] == "golden" and listed["triage-INC-4412"]["has_branch"]
    assert listed[live["run_id"]]["source"] == "run"

    started = live_client.post("/api/runs", json={"incident_id": "INC-4412", "mode": "replay", "speed": 64})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["replayed"] is True and run["recording"] == "triage-INC-4412" and run["session_id"] == live["session_id"]
    final = finished(live_client, run["run_id"])
    assert final["status"] == "finished" and final["branch"] == "incident/INC-4412-cache-ttl"
    assert final["pr_id"] == "incident/INC-4412-cache-ttl"

    events = live_client.get(f"/api/runs/{run['run_id']}/events").json()
    assert [e["type"] for e in events][0] == "session" and all(e["replayed"] is True for e in events)
    assert len([e for e in events if e["type"] == "tool_call"]) == 11

    [pr] = live_client.get("/api/prs").json()
    assert pr["state"] == "open" and len(pr["commits"]) == 1
    types = [e["type"] for e in live_client.get("/api/timeline").json()]
    assert "run_replayed" in types and types.count("pr_opened") == 2
    assert not (settings.runs_dir / run["run_id"] / "branch.patch").exists(), "replays are not re-archived"
    assert live_client.get("/api/health").json()["repo"]["branch"] == "incident/INC-4412-cache-ttl", "restored like a live run leaves it"


def test_replay_speed_and_cancel(live_client, settings):
    folder = settings.recordings_dir / "triage-INC-4412"
    folder.mkdir(parents=True)
    fixture = (settings.repo_root.parents[0] / "nothing")  # unused; keep path math explicit
    from services.console.tests.conftest import FAKE_CLAUDE
    lines = (FAKE_CLAUDE.parent / "stream_json_sample.jsonl").read_text().replace("__SESSION__", "rec").splitlines()
    folder.joinpath("run.jsonl").write_text("".join(json.dumps({"t": i * 2000, "line": line}) + "\n" for i, line in enumerate(lines)))
    folder.joinpath("meta.json").write_text(json.dumps({"incident_id": "INC-4412", "session_id": "rec", "branch": None}))

    run = live_client.post("/api/runs", json={"incident_id": "INC-4412", "mode": "replay", "recording": "golden", "speed": 1}).json()
    assert live_client.post(f"/api/runs/{run['run_id']}/speed", json={"speed": 32}).json()["speed"] == 32
    wait_until(lambda: len(live_client.get(f"/api/runs/{run['run_id']}/events").json()) >= 2)
    cancelled = live_client.post(f"/api/runs/{run['run_id']}/cancel").json()
    assert cancelled["status"] in ("cancelling", "cancelled")
    assert finished(live_client, run["run_id"])["status"] == "cancelled"

    missing = live_client.post("/api/runs", json={"incident_id": "INC-9999", "mode": "replay"})
    assert missing.status_code == 404


def test_speed_is_rejected_for_live_runs(live_client, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.1")
    run = live_client.post("/api/runs", json={"incident_id": "INC-4412"}).json()
    assert live_client.post(f"/api/runs/{run['run_id']}/speed", json={"speed": 4}).status_code == 400
    live_client.post(f"/api/runs/{run['run_id']}/cancel")
    finished(live_client, run["run_id"])
