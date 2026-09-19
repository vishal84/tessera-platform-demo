"""The data-scientist act, recorded and played back.

The incident act's equivalent is test_replay.py; this is deliberately shaped
the same, because the whole point of `tracks.py` is that the two beats run
through one machine.
"""

import json
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from services.console.app import create_app
from services.console.models import NOTEBOOK_03
from services.console.settings import Settings
from services.console.tests.conftest import FAKE_CLAUDE, git
from services.console.tests.test_models import seed_registry
from services.console.tests.test_runner import finished

MODEL = "fraud-v3-candidate"
BRANCH = "ml/TESS-2310-point-in-time-features"
PR_FILE = "ml__TESS-2310-point-in-time-features.md"
START = {"track": "model", "subject_id": MODEL}


@pytest.fixture
def model_settings(demo_repo):
    seed_registry(demo_repo)
    path = demo_repo / "ml" / "registry" / "models.json"
    data = json.loads(path.read_text())
    data["models"][1]["ticket"] = "TESS-2310"
    path.write_text(json.dumps(data))
    git(demo_repo, "add", "-A")
    git(demo_repo, "commit", "-q", "-m", "chore(ml): seed the registry")
    return Settings(
        repo_root=demo_repo, claude_bin=str(FAKE_CLAUDE), gate_python=(sys.executable,),
        health_interval_seconds=0.05, audit_interval_seconds=0.05, poll_interval_seconds=0.05,
        run_timeout_seconds=20,
    )


@pytest.fixture
def model_client(model_settings):
    with TestClient(create_app(model_settings)) as tc:
        yield tc


def test_the_recorded_investigation_replays_and_leaves_the_fix_in_the_tree(
        model_client, model_settings, demo_repo, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")

    live = model_client.post("/api/runs", json=START)
    assert live.status_code == 201, live.text
    live = live.json()
    assert live["track"] == "model" and live["subject_id"] == MODEL
    assert live["incident_id"] is None, "a model run is not an incident"
    done = finished(model_client, live["run_id"])
    assert done["status"] == "finished", done.get("error")
    assert done["branch"] == BRANCH, "found through the ticket, not the model name"

    # The phases the stream produced, in the order the stepper will light them.
    phases = [e["phase"] for e in model_client.get(f"/api/runs/{live['run_id']}/events").json()
              if e["type"] == "phase"]
    assert phases == ["shadow", "reproduce", "leakage", "aggregates", "gates", "card", "pr"]

    # Promote the run to the committed golden recording, and carry the executed
    # notebook out of band rather than as a patch hunk against a seeded file.
    golden = model_settings.recordings_dir / f"validate-{MODEL}"
    shutil.copytree(model_settings.runs_dir / live["run_id"], golden)
    (golden / "artifacts").mkdir()
    (golden / "artifacts" / "notebook.executed.ipynb").write_text('{"executed": true}')
    meta = json.loads((golden / "meta.json").read_text())
    meta["restore_files"] = [{"from": "artifacts/notebook.executed.ipynb", "to": NOTEBOOK_03}]
    (golden / "meta.json").write_text(json.dumps(meta))

    # Back to the start: no branch, no PR, none of the deliverables.
    git(demo_repo, "checkout", "-q", "main")
    git(demo_repo, "branch", "-D", BRANCH)
    (model_settings.prs_dir / PR_FILE).unlink()
    assert not (demo_repo / "ml" / "validation").exists()
    assert model_client.get("/api/prs").json() == []

    listed = {r["name"]: r for r in model_client.get("/api/recordings").json()}
    assert listed[f"validate-{MODEL}"]["source"] == "golden"
    assert listed[f"validate-{MODEL}"]["track"] == "model"
    assert listed[f"validate-{MODEL}"]["subject_id"] == MODEL

    # Replay resolves "golden" by track and subject, not by an incident id.
    started = model_client.post("/api/runs", json={**START, "mode": "replay", "speed": 64})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["replayed"] is True and run["recording"] == f"validate-{MODEL}"
    final = finished(model_client, run["run_id"])
    assert final["status"] == "finished" and final["branch"] == BRANCH

    events = model_client.get(f"/api/runs/{run['run_id']}/events").json()
    assert all(e["replayed"] is True for e in events)
    assert [e["phase"] for e in events if e["type"] == "phase"] == phases

    # What the beats that follow need: the branch restored and checked out, the
    # PR back, the deliverables on disk, and the notebook showing its outputs.
    assert model_client.get("/api/health").json()["repo"]["branch"] == BRANCH
    assert (demo_repo / "ml" / "validation" / "leakage.py").is_file()
    assert (demo_repo / "ml" / "features" / "aggregates.py").is_file()
    assert (demo_repo / "ml" / "fraud" / "MODEL_CARD.md").is_file()
    assert json.loads((demo_repo / NOTEBOOK_03).read_text()) == {"executed": True}

    [pr] = model_client.get("/api/prs").json()
    assert pr["branch"] == BRANCH and pr["track"] == "model" and pr["ticket"] == "TESS-2310"
    assert pr["incident_id"] is None, "and so it stays off the incident page"

    types = [e["type"] for e in model_client.get("/api/timeline").json()]
    assert "investigation_started" in types and "run_replayed" in types


def test_the_gates_have_something_to_run_against_after_a_replay(model_client, model_settings, demo_repo, monkeypatch):
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")
    live = finished(model_client, model_client.post("/api/runs", json=START).json()["run_id"])
    assert live["status"] == "finished"

    registry = model_client.get("/api/models").json()
    assert registry["validation_present"] is True
    assert registry["model_card_present"] is True

    # The artifacts the console watches for, on the timeline under the ds persona.
    console = model_client.app.state.console
    console.artifacts.scan()
    console.artifacts.scan()
    fired = {e["type"] for e in model_client.get("/api/timeline").json()}
    assert {"gates_implemented", "model_card_added", "aggregates_added"} <= fired


def test_preflight_refuses_to_record_over_an_answer_that_is_already_there(model_client, demo_repo):
    (demo_repo / "ml" / "validation").mkdir(parents=True)
    (demo_repo / "ml" / "validation" / "leakage.py").write_text("# already done\n")
    git(demo_repo, "add", "-A")
    git(demo_repo, "commit", "-q", "-m", "chore: pretend the work is done")

    refused = model_client.post("/api/runs", json=START)
    assert refused.status_code == 412
    details = refused.json()["error"]["details"]
    assert any("ml/validation/" in d for d in details), details


def test_an_unknown_candidate_is_refused(model_client):
    refused = model_client.post("/api/runs", json={"track": "model", "subject_id": "fraud-v9"})
    assert refused.status_code == 412
    assert any("fraud-v9" in d for d in refused.json()["error"]["details"])


def test_a_run_needs_a_subject(model_client):
    assert model_client.post("/api/runs", json={"mode": "live"}).status_code == 422


def test_the_prompts_are_filled_in_and_come_from_the_workflow(model_client):
    contract = model_client.get(f"/api/models/{MODEL}/contract").json()
    assert contract["source"] == ".github/workflows/claude-model-validation.yml"
    assert len(contract["prompt_parts"]) == 2
    investigate = contract["prompt_parts"][0]
    assert MODEL in investigate and "{model}" not in investigate, "meant to be pasted, not templated"
    assert "NotebookEdit" in contract["allowed_tools"]


def test_the_incident_contract_is_still_templated(model_client):
    """/runs/contract describes a shape; /models/<name>/contract describes a run."""
    contract = model_client.get("/api/runs/contract").json()
    assert contract["prompt"].startswith("Run /triage-incident {incident_id}")
    assert contract["track"] == "incident"


def test_a_timeout_that_still_produced_a_pr_is_not_a_failure(model_client, model_settings, monkeypatch):
    """A run can overrun the clock on the way out. The recording is still usable,
    so it finalizes as finished-with-warning rather than a hard failure."""
    from services.console.runner import Run

    # _finalize re-derives pr_id from disk, so the PR has to really be there --
    # which is the whole point: it landed before the clock ran out.
    model_settings.prs_dir.mkdir(parents=True, exist_ok=True)
    (model_settings.prs_dir / PR_FILE).write_text(
        f"---\ntitle: late but complete\nbranch: {BRANCH}\nbase: main\n---\nbody\n")

    runner = model_client.app.state.console.runner
    run = Run(run_id="run_late", track="model", subject_id=MODEL, mode="live")
    runner.runs[run.run_id] = run
    runner.active = run
    run.branch = BRANCH
    runner._finalize(run, "failed", {"kind": "timeout", "message": "no result after 2700s", "stderr_tail": ""})

    assert run.status == "finished"
    assert run.error is None
    assert "timeout" in (run.warning or "")


def test_replay_restores_over_an_executed_notebook(model_client, model_settings, demo_repo, monkeypatch):
    """The beat executes notebook 03 in place before anyone reaches for the
    fallback. A restore that refuses on a dirty tree cannot run at the one
    moment it exists for, so it discards tracked changes instead."""
    monkeypatch.setenv("TESSERA_FAKE_MAKE_PR", "1")
    live = finished(model_client, model_client.post("/api/runs", json=START).json()["run_id"])
    assert live["status"] == "finished"

    golden = model_settings.recordings_dir / f"validate-{MODEL}"
    shutil.copytree(model_settings.runs_dir / live["run_id"], golden)
    git(demo_repo, "checkout", "-q", "main")
    git(demo_repo, "branch", "-D", BRANCH)
    (model_settings.prs_dir / PR_FILE).unlink()

    # What the presenter's tree looks like mid-beat: the notebook has been run.
    notebook = demo_repo / NOTEBOOK_03
    notebook.write_text(json.dumps({"cells": [{"cell_type": "code", "source": "executed",
                                               "outputs": [{"output_type": "stream"}]}]}))
    assert git(demo_repo, "status", "--porcelain").strip(), "tree is dirty, as it would be on stage"

    run = model_client.post("/api/runs", json={**START, "mode": "replay", "speed": 64}).json()
    final = finished(model_client, run["run_id"])

    assert final["status"] == "finished"
    assert final["branch"] == BRANCH, "the branch restored despite the dirty tree"
    assert (demo_repo / "ml" / "validation" / "leakage.py").is_file(), "the gates have something to run"
    assert (demo_repo / "ml" / "fraud" / "MODEL_CARD.md").is_file()
    assert model_client.get("/api/prs").json(), "and the PR is back for the merge beat"
