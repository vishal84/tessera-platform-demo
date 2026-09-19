"""JSON API. Every handler reaches shared state through `console(request)`."""

from __future__ import annotations

import asyncio
import functools
import subprocess
import time

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from typing import Literal

from . import guardrails, incidents, models, replay, sse, tracks
from .errors import ApiError
from .prs import use_local_prs
from .runner import workflow_contract
from .timeline import PERSONAS

router = APIRouter()


def console(request: Request):
    return request.app.state.console


# --- health ------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def _claude_version(binary: str, cwd: str) -> str | None:
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10, cwd=cwd)
        return proc.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


_JUPYTER_CACHE: dict[str, tuple[float, bool]] = {}


def jupyter_reachable(url: str, ttl: float = 5.0) -> bool:
    cached = _JUPYTER_CACHE.get(url)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]
    try:
        ok = httpx.get(f"{url.rstrip('/')}/api", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        ok = False
    _JUPYTER_CACHE[url] = (time.monotonic(), ok)
    return ok


@router.get("/health")
async def health(request: Request):
    c = console(request)
    git, settings = c.git, c.settings
    run = c.active_run
    return {
        "status": "ok",
        "repo": {"root": str(settings.repo_root), "head": git.short(), "branch": git.current_branch(),
                 "clean": git.is_clean()},
        "claude": {"bin": settings.claude_bin, "version": await asyncio.to_thread(_claude_version, settings.claude_bin, str(settings.repo_root))},
        "jupyter": {"url": settings.jupyter_url, "reachable": await asyncio.to_thread(jupyter_reachable, settings.jupyter_url)},
        "run": {"active": run is not None, "run_id": getattr(run, "run_id", None)},
        "provider": "github" if git.has_remote() else "local",
        "persona": c.persona,
    }


@router.get("/gateway/health")
async def gateway_health(request: Request):
    return await asyncio.to_thread(console(request).health.refresh)


# --- incidents ---------------------------------------------------------------

@router.get("/incidents")
def list_incidents(request: Request):
    c = console(request)
    return [{**inc, "status": c.incident_status(inc["id"])} for inc in incidents.list_incidents(c.settings)]


@router.get("/incidents/{incident_id}")
def get_incident(request: Request, incident_id: str):
    c = console(request)
    bundle = incidents.load_bundle(c.settings, incident_id)
    if bundle is None:
        raise ApiError(404, "not_found", f"no evidence bundle for {incident_id}")
    return {**bundle, "status": c.incident_status(incident_id)}


# --- timeline & persona ------------------------------------------------------

class TimelineIn(BaseModel):
    type: str
    persona: str
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = None
    refs: dict = Field(default_factory=dict)


@router.get("/timeline")
def get_timeline(request: Request):
    return console(request).timeline.load()


@router.post("/timeline", status_code=201)
def post_timeline(request: Request, body: TimelineIn):
    c = console(request)
    try:
        event = c.timeline.append(body.type, body.persona, body.title, body.detail, body.refs)
    except ValueError as exc:
        raise ApiError(400, "invalid_event", str(exc)) from exc
    if body.persona in ("sre", "swe", "ds"):
        c.persona = body.persona
    return event


class PersonaIn(BaseModel):
    persona: str


@router.post("/persona")
def set_persona(request: Request, body: PersonaIn):
    if body.persona not in PERSONAS:
        raise ApiError(400, "invalid_persona", f"persona must be one of {PERSONAS}")
    console(request).persona = body.persona
    return {"persona": body.persona}


# --- guardrails --------------------------------------------------------------

@router.get("/guardrails/policy")
async def guardrail_policy(request: Request):
    return await asyncio.to_thread(guardrails.policy, console(request).settings)


@router.get("/guardrails/audit")
def guardrail_audit(request: Request, since: str | None = None, decision: str | None = None,
                    limit: int = 200):
    decisions = {d.strip() for d in decision.split(",") if d.strip()} if decision else None
    return console(request).audit.query(since=since, decisions=decisions, limit=max(1, min(limit, 2000)))


# --- events ------------------------------------------------------------------

@router.get("/events")
async def events(request: Request):
    return sse.response(console(request).bus, request)


# --- runs --------------------------------------------------------------------

class RunIn(BaseModel):
    # `incident_id` is the original spelling and still works on its own. A model
    # run sends `track` and `subject_id` instead.
    incident_id: str | None = None
    track: Literal["incident", "model"] | None = None
    subject_id: str | None = None
    mode: Literal["live", "replay"] = "live"
    recording: str | None = None
    speed: float = 1.0
    record: bool = True

    def resolved(self) -> tuple[tracks.Track, str]:
        subject = self.subject_id or self.incident_id
        if not subject:
            raise ApiError(422, "no_subject", "a run needs either incident_id or subject_id")
        return tracks.get(self.track) if self.track else tracks.for_subject(subject), subject


@router.get("/runs/contract")
def run_contract(request: Request, track: str | None = None):
    """What a live run will execute: the prompt, allowlist and flags, and where they come from."""
    c = console(request)
    chosen = tracks.get(track)
    contract = workflow_contract(c.settings, chosen)
    from .runner import build_argv, prompt_parts
    local = use_local_prs(c.settings, c.git)
    subject = "INC-0000" if chosen.kind == tracks.INCIDENT else "<model>"
    argv = build_argv(c.settings, subject, "<session-id>", local=local, track=chosen)
    return {**contract, "argv": argv, "provider": "local" if local else "github",
            "prompt_parts": prompt_parts(contract), "model": c.settings.claude_model}


@router.post("/runs", status_code=201)
async def start_run(request: Request, body: RunIn):
    c = console(request)
    track, subject = body.resolved()
    if body.mode == "replay":
        run = await c.runner.start_replay(subject, body.recording or replay.GOLDEN, body.speed, track=track)
    else:
        run = await c.runner.start_live(subject, record=body.record, track=track)
    return run.meta()


@router.get("/runs")
def list_runs(request: Request):
    return console(request).runner.list()


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str):
    return console(request).runner.get(run_id).meta()


@router.get("/runs/{run_id}/events")
def run_events(request: Request, run_id: str, after: int = 0):
    run = console(request).runner.get(run_id)
    return [event for event in run.events if event["seq"] > after]


@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str):
    run = await console(request).runner.cancel(run_id)
    return run.meta()


class SpeedIn(BaseModel):
    speed: float = Field(gt=0, le=64)


@router.post("/runs/{run_id}/speed")
def run_speed(request: Request, run_id: str, body: SpeedIn):
    return console(request).runner.set_speed(run_id, body.speed).meta()


@router.get("/recordings")
def recordings(request: Request):
    return replay.catalog(console(request).settings)


# --- pull requests -------------------------------------------------------------

class PersonaAction(BaseModel):
    persona: str = "swe"


REVIEW_PROMPT = (
    "Review the PR on branch {branch}: read {path} for the description, then the diff against main "
    "(git diff main...{branch}). Check it against CLAUDE.md's reliability rules and tell me whether "
    "the fix is separable from the cleanup."
)


@router.get("/prs")
def list_prs(request: Request):
    return [pr.as_dict() for pr in console(request).prs.list()]


@router.get("/prs/{pr_id:path}/diff")
def pr_diff(request: Request, pr_id: str):
    return console(request).prs.diff(pr_id)


@router.post("/prs/{pr_id:path}/review-request")
def pr_review_request(request: Request, pr_id: str, body: PersonaAction):
    c = console(request)
    pr = c.prs.get(pr_id)
    if body.persona in ("sre", "swe", "ds"):
        c.persona = body.persona
    prompt = REVIEW_PROMPT.format(branch=pr.branch, path=pr.path or f".tessera/prs/{pr.branch.replace('/', '__')}.md")
    c.timeline.append("review_requested", body.persona if body.persona in PERSONAS else "swe",
                      f"Review requested on {pr.branch}", detail="Hand-off to the desktop app",
                      refs={"pr_id": pr.id, "branch": pr.branch, "incident_id": pr.incident_id})
    return {"ok": True, "prompt": prompt, "pr": pr.as_dict()}


@router.post("/prs/{pr_id:path}/merge")
async def pr_merge(request: Request, pr_id: str, body: PersonaAction):
    c = console(request)
    pr = c.prs.get(pr_id)
    sha = await asyncio.to_thread(c.prs.merge, pr_id)
    persona = body.persona if body.persona in PERSONAS else "swe"
    c.timeline.append("merged", persona, f"Merged {pr.branch} into {pr.base}",
                      detail=f"{pr.title} — main is now {sha[:7]}",
                      refs={"pr_id": pr.id, "branch": pr.branch, "incident_id": pr.incident_id, "sha": sha[:7]})
    await asyncio.to_thread(c.watcher.scan)
    health = await asyncio.to_thread(c.health.refresh)
    return {"merged_sha": sha, "production": health["production"]}


@router.get("/prs/{pr_id:path}")
def get_pr(request: Request, pr_id: str):
    return console(request).prs.get(pr_id).as_dict()


# --- models ------------------------------------------------------------------

@router.get("/models")
def get_models(request: Request):
    return models.registry(console(request).settings)


@router.get("/models/{name}/contract")
def model_contract(request: Request, name: str):
    """The prompts the data scientist runs, read from the workflow rather than retyped.

    Filled in for this candidate, unlike /runs/contract: these are meant to be
    copied into the desktop app, and a placeholder is not something you can paste.
    """
    c = console(request)
    models.registry(c.settings)          # 404 if there is no registry
    from .runner import build_argv, fill, prompt_parts

    chosen = tracks.get(tracks.MODEL)
    contract = workflow_contract(c.settings, chosen)
    local = use_local_prs(c.settings, c.git)
    return {
        **contract,
        "prompt": fill(contract["prompt"], name),
        "prompt_parts": [fill(part, name) for part in prompt_parts(contract)],
        "argv": build_argv(c.settings, name, "<session-id>", local=local, track=chosen),
        "provider": "local" if local else "github",
        "model": c.settings.claude_model,
        "subject_id": name,
    }


@router.get("/models/{name}/shadow")
def get_shadow(request: Request, name: str):
    return models.shadow(console(request).settings, name)


@router.get("/models/{name}/notebook-url")
async def get_notebook_url(request: Request, name: str):
    c = console(request)
    reachable = await asyncio.to_thread(jupyter_reachable, c.settings.jupyter_url)
    return models.notebook_url(c.settings, name, reachable)


class GatesIn(BaseModel):
    persona: str = "ds"


@router.post("/models/{name}/gates", status_code=202)
async def run_gates(request: Request, name: str, body: GatesIn | None = None):
    c = console(request)
    models.registry(c.settings)   # 404 if there is no registry
    persona = body.persona if body and body.persona in ("sre", "swe", "ds") else "ds"
    c.persona = persona
    return await c.gates.start(name, persona)


@router.get("/models/{name}/gates")
def get_gates(request: Request, name: str):
    return console(request).gates.latest(name)


@router.post("/models/{name}/proof")
async def run_proof(request: Request, name: str):
    c = console(request)
    result = await asyncio.to_thread(models.proof, c.settings, list(c.settings.gate_python) if c.settings.gate_python else None)
    c.timeline.append("note", "ds", f"Negative proof run for {name}: pytest exit {result['exit_code']}",
                      detail=", ".join(f"{t['outcome']} {t['name'].split('::')[-1]}" for t in result["tests"][:6]) or None,
                      refs={"model": name})
    return result
