"""
Runs `claude -p` exactly the way the GitHub Action does, streams its
stream-json output into the event bus, records it, and notices what it left
behind (a branch, a PR file).

Two tracks run through here -- the SRE's incident triage and the data
scientist's model investigation. They differ only in the workflow file their
argv is derived from and in what counts as progress; see `tracks.py`. The argv
is derived from that workflow at run time so the console cannot drift from the
automation it stands in for. The only addition in local mode is a system-prompt
note explaining how to "open a PR" without a remote.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import replay, tracks
from .bus import EventBus, now_iso
from .errors import ApiError
from .gitops import Git, GitError
from .prs import pr_filename, use_local_prs
from .settings import Settings
from .stream_json import StreamParser
from .timeline import Timeline
from .tracks import Track

LOCAL_PR_CONTRACT = (
    "This repository's pull requests are reviewed locally, so `gh pr create` is unavailable "
    "and nothing may be pushed to the remote. "
    "After committing on your working branch, open the pull request by writing it to a file: "
    ".tessera/prs/<branch name with every \"/\" replaced by \"__\">.md -- start with a YAML "
    "front-matter block containing `title`, `branch` and `base: main`, then the pull request "
    "body in markdown, including the postmortem draft. Do not push. Do not merge."
)

_MAX_TURNS = re.compile(r"--max-turns\s+(\d+)")
_ALLOWED = re.compile(r"--allowedTools\s+\"([^\"]+)\"")
_AUTH_ERROR = re.compile(r"not logged in|invalid api key|authentication|please run /login|unauthorized", re.I)
_PROMPT_SECTION = re.compile(r"^##\s+\d+\.[^\n]*\n(.*?)(?=^##\s+\d+\.|\Z)", re.M | re.S)


def fill(prompt: str, subject_id: str) -> str:
    """Substitute the subject under whichever name the prompt happens to use."""
    aliases = {"incident_id": subject_id, "subject_id": subject_id, "subject": subject_id, "model": subject_id}
    try:
        return prompt.format(**aliases)
    except (KeyError, IndexError, ValueError):
        return prompt          # a prompt with literal braces in it; better whole than mangled


def workflow_contract(settings: Settings, track: Track | None = None) -> dict:
    """Prompt, allowlist and turn budget, read from this track's workflow file."""
    track = track or tracks.get(None)
    contract = {"prompt": track.fallback_prompt, "allowed_tools": track.fallback_allowed,
                "max_turns": settings.max_turns, "source": "fallback", "track": track.kind}
    path = settings.workflows_dir / track.workflow
    if not path.is_file():
        return contract
    try:
        doc = yaml.safe_load(path.read_text()) or {}
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("anthropics/claude-code-action"):
                    with_ = step.get("with") or {}
                    prompt = str(with_.get("prompt") or "")
                    args = str(with_.get("claude_args") or "")
                    if prompt:
                        contract["prompt"] = prompt.replace(track.env_placeholder, "{" + track.prompt_key + "}").strip()
                    if match := _ALLOWED.search(args):
                        contract["allowed_tools"] = match.group(1)
                    if match := _MAX_TURNS.search(args):
                        contract["max_turns"] = int(match.group(1))
                    contract["source"] = str(path.relative_to(settings.repo_root))
    except (yaml.YAMLError, AttributeError):
        pass
    return contract


def prompt_parts(contract: dict) -> list[str]:
    """The numbered sections of a prompt, for a UI that offers them one at a time.

    The data-scientist beat is two prompts -- investigate, then productionize --
    and the console shows them as two buttons. Splitting the workflow's own
    prompt keeps what the presenter types and what CI runs provably the same
    text instead of two strings that drift.
    """
    body = str(contract.get("prompt") or "")
    parts = [match.group(1).strip() for match in _PROMPT_SECTION.finditer(body)]
    return [p for p in parts if p] or [body.strip()]


def build_argv(settings: Settings, subject_id: str, session_id: str, local: bool,
               track: Track | None = None) -> list[str]:
    track = track or tracks.get(None)
    contract = workflow_contract(settings, track)
    allowed = contract["allowed_tools"]
    if local:
        allowed = ",".join(t for t in allowed.split(",") if not t.startswith("Bash(gh pr create"))
    argv = [
        settings.claude_bin, "-p", fill(contract["prompt"], subject_id),
        "--output-format", "stream-json", "--verbose", "--include-hook-events",
        "--permission-mode", "acceptEdits", "--permission-prompts", "none",
        "--allowedTools", allowed,
        "--max-turns", str(contract["max_turns"]),
        "--max-budget-usd", f"{settings.max_budget_usd:g}",
        "--session-id", session_id,
    ]
    # Which model recorded a run is part of what the recording is evidence of,
    # so it is configuration rather than something hardcoded here.
    if settings.claude_model:
        argv += ["--model", settings.claude_model]
    if local:
        argv += ["--append-system-prompt", LOCAL_PR_CONTRACT]
    return argv


@dataclass
class Run:
    run_id: str
    incident_id: str | None = None   # the incident track's subject; None for a model run
    mode: str = "live"             # live | replay
    track: str = tracks.INCIDENT   # the beat this run belongs to
    subject_id: str = ""           # what is being worked on: INC-4412, or fraud-v3-candidate
    status: str = "running"        # running | cancelling | finished | failed | cancelled
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    session_id: str | None = None
    argv: list[str] = field(default_factory=list)
    recording: str | None = None
    speed: float = 1.0
    replayed: bool = False
    num_turns: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    branch: str | None = None
    pr_id: str | None = None
    error: dict | None = None
    warning: str | None = None
    phases: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        # Recordings committed before tracks existed carry only `incident_id`.
        # One field derives from the other so the two can never disagree.
        if not self.subject_id:
            self.subject_id = self.incident_id or ""
        if self.track == tracks.INCIDENT and not self.incident_id:
            self.incident_id = self.subject_id or None

    def meta(self) -> dict:
        data = asdict(self)
        data.pop("events")
        return data


class Runner:
    def __init__(self, settings: Settings, git: Git, bus: EventBus, timeline: Timeline,
                 session_index: dict[str, str], on_artifacts: Callable[[], None] | None = None) -> None:
        self.settings, self.git, self.bus, self.timeline = settings, git, bus, timeline
        self.session_index, self.on_artifacts = session_index, on_artifacts
        self.runs: dict[str, Run] = {}
        self.active: Run | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._load_history()

    # --- queries --------------------------------------------------------------
    def list(self) -> list[dict]:
        return [run.meta() for run in sorted(self.runs.values(), key=lambda r: r.started_at)]

    def get(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise ApiError(404, "not_found", f"no run {run_id!r}")
        return run

    def run_for_branch(self, branch: str) -> str | None:
        if self.active and self.active.branch in (None, branch):
            return self.active.run_id
        return next((r.run_id for r in self.runs.values() if r.branch == branch), None)

    def preflight(self, subject_id: str, track: Track | None = None) -> list[str]:
        track = track or tracks.get(None)
        problems = list(track.subject_problems(self.settings, subject_id))
        if not self.git.is_repo():
            return problems + ["not a git repository"]
        if not self.git.is_clean(include_untracked=False):
            problems.append("the working tree has uncommitted changes")
        branch = self.git.current_branch()
        if branch != "main":
            problems.append(f"{branch} is checked out, not main")
        for glob in track.branch_globs(self.settings, subject_id):
            for existing in self.git.branches(glob):
                problems.append(f"branch {existing} already exists")
        if self.settings.prs_dir.exists():
            for glob in track.pr_globs(self.settings, subject_id):
                for pr_file in sorted(self.settings.prs_dir.glob(glob)):
                    problems.append(f"a PR is already open for this {track.kind} ({pr_file.name})")
        binary = self.settings.claude_bin
        if not (Path(binary).is_file() or shutil.which(binary)):
            problems.append(f"claude binary not found: {binary}")
        return problems

    def _branch_for(self, run: Run) -> str | None:
        track = tracks.get(run.track)
        for glob in track.branch_globs(self.settings, run.subject_id):
            found = self.git.branches(glob)
            if found:
                return found[0]
        return None

    # --- starting -------------------------------------------------------------
    def _new_run(self, subject_id: str, mode: str, track: Track) -> Run:
        if self.active is not None:
            raise ApiError(409, "run_active", f"run {self.active.run_id} is still {self.active.status}",
                           details={"run_id": self.active.run_id})
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run = Run(run_id=f"run_{stamp}_{secrets.token_hex(3)}", mode=mode, track=track.kind,
                  subject_id=subject_id,
                  incident_id=subject_id if track.kind == tracks.INCIDENT else None)
        self.runs[run.run_id] = run
        self.active = run
        return run

    def _refs(self, run: Run) -> dict:
        refs = {"run_id": run.run_id, "subject_id": run.subject_id, "track": run.track}
        if run.track == tracks.INCIDENT:
            refs["incident_id"] = run.subject_id
        else:
            refs["model"] = run.subject_id
        return refs

    async def start_live(self, subject_id: str, record: bool = True, track: Track | None = None) -> Run:
        track = track or tracks.get(None)
        if self.active is not None:
            raise ApiError(409, "run_active", f"run {self.active.run_id} is still {self.active.status}",
                           details={"run_id": self.active.run_id})
        problems = self.preflight(subject_id, track)
        if problems:
            raise ApiError(412, "not_ready", "the repository is not ready for a live run", details=problems)
        run = self._new_run(subject_id, "live", track)
        run.session_id = _uuid4()
        run.argv = build_argv(self.settings, subject_id, run.session_id,
                              local=use_local_prs(self.settings, self.git), track=track)
        self.session_index[run.session_id] = run.run_id
        self._write_meta(run)
        self.timeline.append(
            track.started_event, "claude", f"Headless {track.noun} of {subject_id} started",
            detail=f"claude -p, same prompt and tool allowlist as {track.workflow}; hooks active",
            refs=self._refs(run),
        )
        self._publish(run, "run_started")
        self._task = asyncio.create_task(self._execute(run, record), name=f"run:{run.run_id}")
        return run

    async def start_replay(self, subject_id: str, recording: str, speed: float,
                           track: Track | None = None) -> Run:
        track = track or tracks.get(None)
        folder = replay.resolve(self.settings, recording, subject_id, track)
        if folder is None:
            raise ApiError(404, "no_recording", f"no recording {recording!r} for {subject_id}")
        run = self._new_run(subject_id, "replay", track)
        run.recording, run.speed, run.replayed = folder.name, float(speed), True
        meta = json.loads((folder / "meta.json").read_text()) if (folder / "meta.json").is_file() else {}
        run.session_id = meta.get("session_id")
        run.argv = meta.get("argv") or []
        self.timeline.append(
            "run_replayed", "system", f"Playing the recorded {track.noun} of {subject_id} at {speed:g}×",
            detail=f"recording {folder.name}; nothing is being generated live",
            refs=self._refs(run),
        )
        self._publish(run, "run_started")
        self._task = asyncio.create_task(self._replay(run, folder), name=f"replay:{run.run_id}")
        return run

    # --- control --------------------------------------------------------------
    async def cancel(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run.status != "running":
            raise ApiError(409, "not_running", f"run {run_id} is {run.status}")
        run.status = "cancelling"
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        return run

    def set_speed(self, run_id: str, speed: float) -> Run:
        run = self.get(run_id)
        if run.mode != "replay":
            raise ApiError(400, "not_replay", "speed applies to replays only")
        run.speed = max(0.25, min(float(speed), 64.0))
        self._publish(run, "run_progress")
        return run

    # --- execution --------------------------------------------------------------
    async def _execute(self, run: Run, record: bool) -> None:
        run_dir = self.settings.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        recorder = (run_dir / "run.jsonl").open("w", encoding="utf-8") if record else None
        parser = self._parser(run)
        stderr_tail: deque[str] = deque(maxlen=60)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        env["TESSERA_RUN_ID"] = run.run_id
        started = time.monotonic()
        result_seen = False
        timeout = self.settings.run_timeout_seconds or tracks.get(run.track).timeout_seconds

        try:
            proc = await asyncio.create_subprocess_exec(
                *run.argv, cwd=self.settings.repo_root, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=4 * 1024 * 1024,
            )
        except OSError as exc:
            if recorder:
                recorder.close()
            self._finalize(run, "failed", {"kind": "spawn", "message": str(exc), "stderr_tail": ""})
            return
        self._proc = proc

        async def pump_stdout() -> None:
            nonlocal result_seen
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if recorder:
                    recorder.write(json.dumps({"t": int((time.monotonic() - started) * 1000), "line": line}) + "\n")
                    recorder.flush()
                if self._ingest(run, parser, line):
                    result_seen = True

        async def pump_stderr() -> None:
            assert proc.stderr is not None
            async for raw in proc.stderr:
                stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip())

        timed_out = False
        try:
            await asyncio.wait_for(asyncio.gather(pump_stdout(), pump_stderr()), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
        finally:
            returncode = await proc.wait()
            if recorder:
                recorder.close()
            self._proc = None

        tail = "\n".join(stderr_tail)[-2000:]
        if run.status == "cancelling":
            self._finalize(run, "cancelled")
        elif timed_out:
            self._finalize(run, "failed", {"kind": "timeout", "message": f"no result after {timeout:g}s", "stderr_tail": tail})
        elif returncode != 0 or not result_seen:
            kind = "auth" if _AUTH_ERROR.search(tail) else "exit"
            self._finalize(run, "failed", {"kind": kind, "message": f"claude exited with status {returncode}", "stderr_tail": tail})
        elif run.error:
            self._finalize(run, "failed", run.error)
        else:
            self._finalize(run, "finished")

    async def _replay(self, run: Run, folder: Path) -> None:
        parser = self._parser(run)
        try:
            await replay.play(folder, lambda line: self._ingest(run, parser, line),
                              speed=lambda: run.speed, stopped=lambda: run.status != "running")
        finally:
            if run.status == "cancelling":
                self._finalize(run, "cancelled")
            else:
                if self.on_artifacts:      # settle the watcher so a restored PR reads as newly opened
                    self.on_artifacts()
                restored = replay.restore_artifacts(folder, self.settings, self.git)
                if restored["error"]:
                    note = f"restore incomplete -- {restored['error']}"
                elif restored.get("note"):
                    note = restored["note"]
                else:
                    note = "restored recorded branch and PR"
                    if restored.get("discarded"):
                        note += f" (discarded {len(restored['discarded'])} local change(s))"
                # Publish on failure too: a silent failed restore reads as success
                # and leaves the beats that follow with nothing.
                if any((restored["branch"], restored["pr"], restored["files"], restored["error"])):
                    self.bus.publish("run", {"type": "run_progress", "run_id": run.run_id,
                                             **{**restored, "note": note}})
                self._finalize(run, "finished")

    # --- plumbing ---------------------------------------------------------------
    def _ingest(self, run: Run, parser: StreamParser, line: str) -> bool:
        """Parse one stdout line and publish what it yields. Returns True on a result line."""
        saw_result = False
        for event in parser.parse(line):
            if event["type"] == "session" and event.get("session_id"):
                if run.session_id and run.session_id != event["session_id"]:
                    self.session_index[event["session_id"]] = run.run_id
            published = self.bus.publish("activity", {**event, "replayed": run.replayed}).data
            run.events.append(published)
            kind = event["type"]
            if kind == "phase":
                run.phases.append(event["phase"])
                self._phase_timeline(run, event["phase"])
            elif kind == "result":
                saw_result = True
                run.num_turns, run.cost_usd, run.duration_ms = event.get("num_turns"), event.get("cost_usd"), event.get("duration_ms")
                if event.get("is_error"):
                    run.error = {"kind": "result", "message": event.get("subtype") or "error result",
                                 "stderr_tail": event.get("result_text", "")[:500]}
            elif kind == "hook" and run.replayed and event.get("decision"):
                hook = "pii_scan" if event.get("hook_event_name") == "PostToolUse" else "protect_secrets"
                self.bus.publish("audit", {
                    "hook": hook, "event": event.get("hook_event_name"), "session_id": run.session_id,
                    "tool_name": event.get("tool_name"), "target": None, "decision": event["decision"],
                    "reason": (event.get("stderr_head") or "")[:120] or None,
                    "source": "replay", "run_id": run.run_id,
                })
        return saw_result

    def _parser(self, run: Run) -> StreamParser:
        track = tracks.get(run.track)
        return StreamParser(run.run_id, phases=track.phases, classifier=track.classifier)

    def _phase_timeline(self, run: Run, phase: str) -> None:
        note = tracks.get(run.track).phase_timeline.get(phase)
        if note is None:
            return
        kind, title, detail = note
        self.timeline.append(kind, "claude", title, detail=detail, refs=self._refs(run))

    def _finalize(self, run: Run, status: str, error: dict | None = None) -> None:
        run.ended_at = now_iso()
        run.branch = (self._branch_for(run) if self.git.is_repo() else None) or run.branch
        if self.on_artifacts:
            try:
                self.on_artifacts()
            except Exception:  # noqa: BLE001
                pass
        if run.branch:
            pr_file = self.settings.prs_dir / pr_filename(run.branch)
            run.pr_id = run.branch if pr_file.is_file() else None
            if run.mode == "live":
                self._archive(run, pr_file)
        error = error or run.error if status == "failed" else None
        if status == "failed" and run.pr_id and error and error.get("kind") in ("exit", "result", "timeout"):
            # It got there -- a branch and a PR exist -- but e.g. ran out of turns, or
            # ran past the clock, on the way out. That is a finished run worth a
            # warning, not a failure: the recording it left behind is usable.
            status, run.warning, error = "finished", f"{error.get('kind')}: {error.get('message')}", None
        run.status, run.error = status, error
        self._write_meta(run)
        self.active = None
        self._task = None
        kind = {"finished": "run_finished", "failed": "run_failed", "cancelled": "run_cancelled"}[status]
        self._publish(run, kind)
        if status == "failed":
            self.timeline.append("run_failed", "system", f"Headless run failed ({(error or {}).get('kind', 'error')})",
                                 detail=(error or {}).get("message"), refs=self._refs(run))
        elif status == "cancelled":
            self.timeline.append("run_cancelled", "system", "Headless run cancelled by the presenter",
                                 refs=self._refs(run))

    def _archive(self, run: Run, pr_file: Path) -> None:
        run_dir = self.settings.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if pr_file.is_file():
            shutil.copy2(pr_file, run_dir / "pr.md")
        try:
            if self.git.log(f"main..{run.branch}", limit=1):
                (run_dir / "branch.patch").write_text(self.git.format_patch("main", run.branch), encoding="utf-8")
        except GitError:
            pass

    def _write_meta(self, run: Run) -> None:
        run_dir = self.settings.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps(run.meta(), indent=2) + "\n")

    def _publish(self, run: Run, kind: str) -> None:
        self.bus.publish("run", {"type": kind, **run.meta()})

    def _load_history(self) -> None:
        if not self.settings.runs_dir.exists():
            return
        for meta_path in sorted(self.settings.runs_dir.glob("*/meta.json")):
            try:
                data = json.loads(meta_path.read_text())
                run = Run(**{k: v for k, v in data.items() if k in Run.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                continue
            if run.status in ("running", "cancelling"):   # a previous process died mid-run
                run.status, run.error = "failed", {"kind": "exit", "message": "console restarted during the run", "stderr_tail": ""}
            self.runs[run.run_id] = run
            if run.session_id:
                self.session_index[run.session_id] = run.run_id


def _uuid4() -> str:
    import uuid
    return str(uuid.uuid4())
