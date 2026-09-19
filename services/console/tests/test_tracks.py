"""The two tracks, and the invariants that keep one from breaking the other."""

import json

from services.console import tracks
from services.console.runner import Run, build_argv, prompt_parts, workflow_contract
from services.console.settings import Settings
from services.console.stream_json import classify_incident, classify_model
from services.console.timeline import TYPES
from services.console.tests.test_models import seed_registry


def test_every_timeline_type_a_track_can_emit_is_a_known_type():
    """`_phase_timeline` runs inside the replay's ingest callback and `Timeline.append`
    raises on an unknown type -- an unlisted one would abort a replay mid-stream."""
    for track in tracks.TRACKS.values():
        assert track.started_event in TYPES, track.kind
        for phase, (kind, _title, _detail) in track.phase_timeline.items():
            assert kind in TYPES, f"{track.kind}/{phase} emits unknown type {kind!r}"


def test_every_phase_a_track_names_is_in_its_phase_tuple():
    for track in tracks.TRACKS.values():
        for phase in track.phase_timeline:
            assert phase in track.phases, f"{track.kind} has no phase {phase!r}"


def test_unknown_track_falls_back_to_the_incident_one():
    assert tracks.get(None).kind == "incident"
    assert tracks.get("nonsense").kind == "incident"
    assert tracks.for_subject("INC-4412").kind == "incident"
    assert tracks.for_subject("fraud-v3-candidate").kind == "model"


def test_model_branch_globs_cover_both_the_ticket_and_the_model(demo_repo):
    seed_registry(demo_repo)
    path = demo_repo / "ml" / "registry" / "models.json"
    data = json.loads(path.read_text())
    data["models"][1]["ticket"] = "TESS-2310"
    path.write_text(json.dumps(data))
    settings = Settings(repo_root=demo_repo)

    globs = tracks.get("model").branch_globs(settings, "fraud-v3-candidate")
    assert "ml/TESS-2310-*" in globs, "the branch is named for the ticket"
    assert "ml/fraud-v3-candidate-*" in globs, "but the subject is the model"
    assert tracks.get("model").pr_globs(settings, "fraud-v3-candidate") == [
        "ml__fraud-v3-candidate-*.md", "ml__TESS-2310-*.md"]


def test_incident_branch_glob_is_unchanged(demo_repo):
    settings = Settings(repo_root=demo_repo)
    assert tracks.get("incident").branch_globs(settings, "INC-4412") == ["incident/INC-4412-*"]


# --- the contract ---------------------------------------------------------------

def test_each_track_parses_its_own_workflow(demo_repo):
    settings = Settings(repo_root=demo_repo)

    incident = workflow_contract(settings, tracks.get("incident"))
    assert incident["source"] == ".github/workflows/claude-incident-fix.yml"
    assert incident["prompt"].startswith("Run /triage-incident {incident_id}")

    model = workflow_contract(settings, tracks.get("model"))
    assert model["source"] == ".github/workflows/claude-model-validation.yml"
    assert "NotebookEdit" in model["allowed_tools"], "without it the notebook beat is silent"
    parts = prompt_parts(model)
    assert len(parts) == 2, "investigate, then productionize"
    assert parts[0].startswith("Open ml/notebooks/03_v3_shadow_investigation.ipynb")
    assert parts[1].startswith("Productionize the finding")


def test_the_model_prompt_is_filled_with_the_subject(demo_repo):
    settings = Settings(repo_root=demo_repo)
    argv = build_argv(settings, "fraud-v3-candidate", "sid", local=True, track=tracks.get("model"))
    prompt = argv[argv.index("-p") + 1]
    assert "fraud-v3-candidate" in prompt and "${{" not in prompt


def test_the_model_is_pinned_only_when_configured(demo_repo):
    plain = build_argv(Settings(repo_root=demo_repo), "INC-4412", "sid", local=True)
    assert "--model" not in plain
    pinned = build_argv(Settings(repo_root=demo_repo, claude_model="claude-fable-5-1"),
                        "INC-4412", "sid", local=True)
    assert pinned[pinned.index("--model") + 1] == "claude-fable-5-1"


# --- classification ---------------------------------------------------------------

def test_the_leaky_notebook_wins_over_the_generic_notebook_rule():
    """Notebook 01 matches both rules. It is where the leak lives, so it must win."""
    assert classify_model("Read", {"file_path": "ml/notebooks/01_fraud_exploration.ipynb"}) == "leakage"
    assert classify_model("Read", {"file_path": "ml/notebooks/03_v3_shadow_investigation.ipynb"}) == "reproduce"


def test_model_classification_covers_each_phase():
    cases = [
        ("shadow", "Read", {"file_path": "ml/registry/shadow/fraud-v3-candidate.json"}),
        ("leakage", "Read", {"file_path": "ml/notebooks/01_fraud_exploration.ipynb"}),
        ("reproduce", "Bash", {"command": "uv run jupyter nbconvert --execute --inplace nb.ipynb"}),
        ("aggregates", "Write", {"file_path": "ml/features/aggregates.py"}),
        ("gates", "Write", {"file_path": "ml/validation/leakage.py"}),
        ("gates", "Bash", {"command": "uv run pytest ml/ -q"}),
        ("card", "Write", {"file_path": "ml/fraud/MODEL_CARD.md"}),
        ("card", "Skill", {"skill": "model-card"}),
        ("pr", "Bash", {"command": "git checkout -b ml/TESS-2310-point-in-time"}),
        ("pr", "Write", {"file_path": ".tessera/prs/ml__TESS-2310-point-in-time.md"}),
    ]
    for expected, tool, tool_input in cases:
        assert classify_model(tool, tool_input) == expected, (tool, tool_input)
    assert set(p for p, _, _ in cases) == set(tracks.get("model").phases)


def test_incident_classification_is_untouched():
    assert classify_incident("Read", {"file_path": "ops/incidents/INC-4412/alert.json"}) == "evidence"
    assert classify_incident("Bash", {"command": "uv run python -m services.risk_gateway.simulation"}) == "prove"
    assert classify_incident("Write", {"file_path": "services/risk_gateway/config.py"}) == "fix"
    assert classify_incident("Read", {"file_path": "ml/registry/shadow/x.json"}) is None


# --- backward compatibility -------------------------------------------------------

def test_a_recording_from_before_tracks_existed_loads_as_an_incident():
    """`demo/recordings/triage-INC-4412/meta.json` has neither `track` nor `subject_id`."""
    legacy = {"run_id": "run_x", "incident_id": "INC-4412", "mode": "live", "status": "finished"}
    run = Run(**{k: v for k, v in legacy.items() if k in Run.__dataclass_fields__})
    assert run.track == "incident"
    assert run.subject_id == "INC-4412"
    assert run.incident_id == "INC-4412"


def test_a_model_run_does_not_pretend_to_be_an_incident():
    run = Run(run_id="run_y", track="model", subject_id="fraud-v3-candidate")
    assert run.incident_id is None, "an incident page must not pick this up"
    assert run.subject_id == "fraud-v3-candidate"


# --- how long a beat is given --------------------------------------------------

def test_each_track_carries_its_own_timeout():
    """15 minutes fits incident triage and does not fit the model investigation."""
    assert tracks.get("incident").timeout_seconds == 15 * 60
    assert tracks.get("model").timeout_seconds == 45 * 60


def test_the_timeout_is_tunable_and_overrides_every_track(monkeypatch):
    assert Settings.from_env().run_timeout_seconds is None, "unset means ask the track"
    monkeypatch.setenv("TESSERA_RUN_TIMEOUT_SECONDS", "1800")
    assert Settings.from_env().run_timeout_seconds == 1800


def test_a_run_resolves_its_timeout_from_settings_then_the_track():
    """The expression the runner uses: an explicit setting wins, else the track."""
    for kind, expected in (("incident", 900), ("model", 2700)):
        settings = Settings(run_timeout_seconds=None)
        assert (settings.run_timeout_seconds or tracks.get(kind).timeout_seconds) == expected
    pinned = Settings(run_timeout_seconds=20)
    assert (pinned.run_timeout_seconds or tracks.get("model").timeout_seconds) == 20, "tests pin it"
