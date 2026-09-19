"""
Two beats, one machine.

The incident track is the SRE's: `/triage-incident INC-4412`, driven by
`.github/workflows/claude-incident-fix.yml`. The model track is the data
scientist's: the TESS-2310 shadow investigation of `fraud-v3-candidate`, driven
by `.github/workflows/claude-model-validation.yml`.

Everything that differs between them is in this file. The recording format, the
player, the parser, the event bus and the replay banner do not know which track
they are serving, which is the point -- one rendering path, two stories. Adding
a third beat should mean adding a `Track` here and nothing else.

A track never carries a prompt or a tool allowlist of its own: it carries the
name of the workflow file those are parsed out of at run time, so the console
cannot drift from the automation it stands in for.

Timeline types are a closed enum (`timeline.TYPES`) and `Timeline.append`
raises on an unknown one. `_phase_timeline` runs inside the replay's ingest
callback, so an unlisted type would abort a replay mid-stream. `test_tracks.py`
asserts every type named here is in that enum; keep it that way.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import ApiError
from .settings import Settings
from .stream_json import (
    INCIDENT_PHASES,
    MODEL_PHASES,
    classify_incident,
    classify_model,
)

INCIDENT = "incident"
MODEL = "model"


@dataclass(frozen=True)
class Track:
    kind: str                      # "incident" | "model"
    persona: str                   # whose beat this is, for the timeline
    noun: str                      # "triage" | "investigation", for event titles
    workflow: str                  # filename under .github/workflows/
    env_placeholder: str           # the ${{ env.X }} the workflow prompt interpolates
    prompt_key: str                # the name that placeholder becomes, e.g. "{incident_id}"
    branch_prefix: str             # "incident/" | "ml/"
    recording_prefix: str          # "triage" | "validate"
    started_event: str             # timeline type when a live run starts
    live_label: str                # the button that starts a live run
    phases: tuple[str, ...]
    classifier: Callable[[str, dict], str | None]
    fallback_prompt: str           # used only when the workflow file is missing
    fallback_allowed: str
    subject_problems: Callable[[Settings, str], list[str]]
    # phase -> (timeline type, title, detail). Types must be in timeline.TYPES.
    phase_timeline: dict[str, tuple[str, str, str | None]] = field(default_factory=dict)
    base: str = "main"
    # How long a live run of this beat is given before it is killed. The
    # incident triage lands around 10 minutes; the model investigation has a
    # notebook execution over 60k rows and four validation modules to write,
    # and reached roughly 40% in 15. Settings.run_timeout_seconds overrides.
    timeout_seconds: float = 15 * 60

    def recording_name(self, subject_id: str) -> str:
        return f"{self.recording_prefix}-{subject_id}"

    def branch_globs(self, settings: Settings, subject_id: str) -> list[str]:
        """Every branch name this track's run might have left behind.

        The model track is a list rather than a string because the branch is
        conventionally named for the ticket (`ml/TESS-2310-...`) while the
        subject is the model (`fraud-v3-candidate`). Accepting both means the
        recording keeps resolving whichever convention the run actually used.
        """
        names = [subject_id, *(t for t in (_ticket(settings, subject_id),) if t and t != subject_id)]
        return [f"{self.branch_prefix}{name}-*" for name in names]

    def pr_globs(self, settings: Settings, subject_id: str) -> list[str]:
        # .tessera/prs/<branch with every "/" replaced by "__">.md
        return [g.replace("/", "__") + ".md" for g in self.branch_globs(settings, subject_id)]


def _ticket(settings: Settings, subject_id: str) -> str | None:
    """The ticket a registry candidate is tracked under, e.g. TESS-2310."""
    path = settings.registry_dir / "models.json"
    if not path.is_file():
        return None
    try:
        models = (json.loads(path.read_text()) or {}).get("models", [])
    except (json.JSONDecodeError, OSError):
        return None
    for entry in models:
        if entry.get("name") == subject_id:
            return entry.get("ticket")
    return None


# --- subject preflight ---------------------------------------------------------
# Only the checks that depend on what is being worked on. The generic ones --
# clean tree, on main, no branch yet, no PR yet, claude on PATH -- stay in the
# runner, because they are true of every track.

def _incident_subject_problems(settings: Settings, subject_id: str) -> list[str]:
    if not (settings.incidents_dir / subject_id / "alert.json").is_file():
        return [f"no evidence bundle at ops/incidents/{subject_id}/"]
    return []


def _model_subject_problems(settings: Settings, subject_id: str) -> list[str]:
    from . import models          # local: models has no need of tracks, and this keeps it that way

    try:
        registry = models.registry(settings)
    except ApiError as exc:
        return [exc.message]
    known = [m["name"] for m in registry["candidates"] if m.get("name")]
    if subject_id not in known:
        return [f"no candidate {subject_id!r} in ml/registry/models.json (have: {', '.join(known) or 'none'})"]
    problems = []
    try:
        models.shadow(settings, subject_id)
    except ApiError:
        problems.append(f"no shadow report at ml/registry/shadow/{subject_id}.json")
    if not (settings.repo_root / models.NOTEBOOK_03).is_file():
        problems.append(f"no investigation notebook at {models.NOTEBOOK_03}")
    # A run that finds the answers already on disk records a misleading stream,
    # and its gates pass before Claude has done anything.
    if models.validation_present(settings):
        problems.append("ml/validation/ is already implemented -- run ./demo/reset-demo.sh")
    if (settings.repo_root / "ml" / "fraud" / "MODEL_CARD.md").is_file():
        problems.append("ml/fraud/MODEL_CARD.md already exists -- run ./demo/reset-demo.sh")
    return problems


# --- the two tracks -------------------------------------------------------------

TRACKS: dict[str, Track] = {
    INCIDENT: Track(
        kind=INCIDENT,
        persona="sre",
        noun="triage",
        workflow="claude-incident-fix.yml",
        env_placeholder="${{ env.INCIDENT_ID }}",
        prompt_key="incident_id",
        branch_prefix="incident/",
        recording_prefix="triage",
        started_event="triage_started",
        live_label="Triage with Claude",
        phases=INCIDENT_PHASES,
        classifier=classify_incident,
        fallback_prompt=(
            "Run /triage-incident {subject_id}\n\nYou are running unattended. Your output is a pull "
            "request for a human to review. You do not merge, you do not deploy, and you do not push "
            "to main. Include the regression test. Verify it fails without your fix."
        ),
        fallback_allowed="Read,Grep,Glob,Edit,Write,Bash(uv run:*),Bash(git:*),Bash(gh pr create:*),Task",
        subject_problems=_incident_subject_problems,
        timeout_seconds=15 * 60,
        phase_timeline={
            "evidence": ("evidence_read", "Claude is reading the evidence bundle", None),
            "prove": ("hypothesis_proven", "Claude is reproducing the failure with the capacity model",
                      "uv run python -m services.risk_gateway.simulation"),
        },
    ),
    MODEL: Track(
        kind=MODEL,
        persona="ds",
        noun="investigation",
        workflow="claude-model-validation.yml",
        env_placeholder="${{ env.MODEL }}",
        prompt_key="model",
        branch_prefix="ml/",
        recording_prefix="validate",
        started_event="investigation_started",
        live_label="Investigate with Claude",
        phases=MODEL_PHASES,
        classifier=classify_model,
        fallback_prompt=(
            "Run /validate-model {subject_id}\n\nYou are running unattended. Your output is a pull "
            "request for a human to review. You do not merge, you do not deploy, and you do not push "
            "to main. Start from the assumption that a large unexplained improvement is a bug, and "
            "quantify whatever you find."
        ),
        fallback_allowed=(
            "Skill,Task,Read,Grep,Glob,Edit,Write,NotebookEdit,"
            "Bash(uv run:*),Bash(git:*),Bash(gh pr create:*)"
        ),
        subject_problems=_model_subject_problems,
        timeout_seconds=45 * 60,
        phase_timeline={
            "shadow": ("shadow_report_opened", "Claude is reading the shadow report",
                       "ml/registry/shadow/"),
            "leakage": ("hypothesis_proven", "Claude is reading the notebook the candidate was trained in",
                        "ml/notebooks/01_fraud_exploration.ipynb -- where card_chargeback_rate is defined"),
            "aggregates": ("note", "Claude is writing the point-in-time feature",
                           "ml/features/aggregates.py"),
            "gates": ("note", "Claude is implementing the validation gates",
                      "the four modules model-validation.yml specifies"),
        },
    ),
}


def get(kind: str | None) -> Track:
    """The track by name. Unknown or missing means the incident track, which came first."""
    return TRACKS.get(kind or INCIDENT, TRACKS[INCIDENT])


def for_subject(subject_id: str) -> Track:
    """Guess the track from the subject. `INC-1234` is an incident; anything else is a model."""
    return TRACKS[INCIDENT] if subject_id.upper().startswith("INC-") else TRACKS[MODEL]
