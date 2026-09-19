import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from services.console.app import create_app
from services.console.bus import EventBus
from services.console.models import ArtifactWatcher, gate_commands
from services.console.settings import Settings
from services.console.timeline import Timeline

SHADOW = {"model": "fraud-v3-candidate", "champion": "fraud-v2", "generated_at": "2026-09-16T08:40:00Z",
          "window": {"start": "2026-07-05", "end": "2026-08-27", "scored_transactions": 18000, "labels": "x"},
          "offline": {"auc": 0.906, "pr_auc": 0.358, "source": "nb01"},
          "shadow": {"auc": 0.699, "pr_auc": 0.071, "by_month": [{"month": "2026-07", "n": 9000, "auc": 0.706}]},
          "champion_same_window": {"auc": 0.778, "pr_auc": 0.164}, "features": ["a"], "feature_serving": {},
          "feature_stats": {"card_chargeback_rate": {"training_nonzero_share": 0.275, "shadow_nonzero_share": 0.142}},
          "status": "blocked", "reason": "worse than champion", "ticket": "TESS-2310"}


def seed_registry(repo: Path) -> None:
    (repo / "ml" / "registry" / "shadow").mkdir(parents=True, exist_ok=True)
    (repo / "ml" / "registry" / "models.json").write_text(json.dumps({"models": [
        {"name": "fraud-v2", "role": "champion", "status": "production"},
        {"name": "fraud-v3-candidate", "role": "candidate", "status": "shadow",
         "investigation_notebook": "ml/notebooks/03_v3_shadow_investigation.ipynb"}]}))
    (repo / "ml" / "registry" / "shadow" / "fraud-v3-candidate.json").write_text(json.dumps(SHADOW))
    (repo / "ml" / "notebooks").mkdir(parents=True, exist_ok=True)
    (repo / "ml" / "notebooks" / "03_v3_shadow_investigation.ipynb").write_text("{}")


def gate_client(demo_repo: Path):
    seed_registry(demo_repo)
    settings = Settings(repo_root=demo_repo, gate_python=(sys.executable,), poll_interval_seconds=0.05,
                        health_interval_seconds=0.05, audit_interval_seconds=0.05)
    return TestClient(create_app(settings))


def wait_gates(client, name, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        gates = client.get(f"/api/models/{name}/gates").json()
        if gates and all(g["status"] not in ("queued", "running") for g in gates):
            return gates
        time.sleep(0.05)
    raise AssertionError("gates never finished")


def test_gate_commands_come_from_the_workflow_file(settings):
    gates = gate_commands(settings)
    assert [g["gate"] for g in gates] == ["leakage", "performance", "drift", "fairness", "model_card"]
    assert gates[0]["command"] == "uv run python -m ml.validation.leakage --fail-on-leak"
    assert gates[3]["command"].endswith("--report fairness.md")


def test_registry_shadow_and_notebook_url(demo_repo):
    client = gate_client(demo_repo)
    body = client.get("/api/models").json()
    assert body["champion"]["name"] == "fraud-v2" and [c["name"] for c in body["candidates"]] == ["fraud-v3-candidate"]
    assert body["validation_present"] is False and body["model_card_present"] is False
    assert client.get("/api/models/fraud-v3-candidate/shadow").json()["shadow"]["auc"] == 0.699
    assert client.get("/api/models/nope/shadow").status_code == 404
    nb = client.get("/api/models/fraud-v3-candidate/notebook-url").json()
    assert nb["url"].startswith("http://localhost:8888/lab/tree/ml/notebooks/03_v3_shadow_investigation.ipynb?token=")
    assert nb["exists"] is True


def test_registry_missing_is_a_404(client):
    response = client.get("/api/models")
    assert response.status_code == 404 and response.json()["error"]["code"] == "no_registry"


def test_gates_report_not_implemented_then_pass_and_blocked(demo_repo):
    with gate_client(demo_repo) as client:
        started = client.post("/api/models/fraud-v3-candidate/gates", json={"persona": "ds"})
        assert started.status_code == 202 and len(started.json()["gates"]) == 5
        gates = wait_gates(client, "fraud-v3-candidate")
        assert [g["status"] for g in gates] == ["not_implemented"] * 4 + ["blocked"]

        validation = demo_repo / "ml" / "validation"
        validation.mkdir(parents=True)
        (validation / "__init__.py").write_text("")
        for module, code in (("leakage", 0), ("performance", 0), ("drift", 1), ("fairness", 0)):
            (validation / f"{module}.py").write_text(f"import sys\nprint('{module} ran', sys.argv[1:])\nsys.exit({code})\n")
        (demo_repo / "ml" / "fraud").mkdir(parents=True, exist_ok=True)
        (demo_repo / "ml" / "fraud" / "MODEL_CARD.md").write_text("# card\n")
        client.post("/api/models/fraud-v3-candidate/gates", json={})
        gates = wait_gates(client, "fraud-v3-candidate")
        assert [g["status"] for g in gates] == ["pass", "pass", "blocked", "pass", "pass"]
        assert "leakage ran ['--fail-on-leak']" in gates[0]["stdout_tail"]

        types = [e["type"] for e in client.get("/api/timeline").json()]
        assert types.count("gates_run") == 2 and "gate_blocked" in types and "gate_passed" in types
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and "gates_implemented" not in types:
            time.sleep(0.05)
            types = [e["type"] for e in client.get("/api/timeline").json()]
        assert "gates_implemented" in types and "model_card_added" in types
        assert client.get("/api/models").json()["validation_present"] is True


def test_artifact_watcher_fires_once_per_artifact(demo_repo, settings):
    seed_registry(demo_repo)
    timeline = Timeline(settings.events_path, EventBus())
    watcher = ArtifactWatcher(settings, timeline, lambda: "ds")
    watcher.prime()
    assert watcher.scan() == []
    (demo_repo / "ml" / "validation").mkdir(parents=True)
    (demo_repo / "ml" / "validation" / "leakage.py").write_text("")
    assert watcher.scan() == ["gates_implemented"]
    assert watcher.scan() == []
    nb = demo_repo / "ml" / "notebooks" / "03_v3_shadow_investigation.ipynb"
    nb.write_text('{"cells": []}')
    assert watcher.scan() == [], "a changed hash must hold for two polls (a mid-write read is not an edit)"
    assert watcher.scan() == ["notebook_updated"]
    assert watcher.scan() == []
    nb.write_text('{"cells": [1]}')
    nb.write_text('{"cells": []}')          # flapped back before the second poll: not an edit
    assert watcher.scan() == [] and watcher.scan() == []
