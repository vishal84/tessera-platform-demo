"""
The model registry page: champion vs candidate, the shadow report, and the
validation gates -- run locally with the exact commands the workflow file
specifies, so the console can never drift from the contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import yaml

from .bus import EventBus, now_iso
from .errors import ApiError
from .settings import Settings
from .timeline import Timeline

_GATE_MODULE = re.compile(r"ml\.validation\.(\w+)")
_NOT_IMPLEMENTED = re.compile(r"No module named ['\"]?ml\.validation|No module named ['\"]?ml['\"]?$", re.M)
_PYTEST_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+(\S+)", re.M)
NOTEBOOK_03 = "ml/notebooks/03_v3_shadow_investigation.ipynb"


# --- registry -----------------------------------------------------------------

def registry(settings: Settings) -> dict:
    path = settings.registry_dir / "models.json"
    if not path.is_file():
        raise ApiError(404, "no_registry", "ml/registry/models.json is missing -- run demo/generate_shadow_report.py")
    models = (json.loads(path.read_text()) or {}).get("models", [])
    return {
        "champion": next((m for m in models if m.get("role") == "champion"), None),
        "candidates": [m for m in models if m.get("role") == "candidate"],
        "from": str(path.relative_to(settings.repo_root)),
        "model_card_present": (settings.repo_root / "ml" / "fraud" / "MODEL_CARD.md").is_file(),
        "validation_present": validation_present(settings),
    }


def validation_present(settings: Settings) -> bool:
    folder = settings.repo_root / "ml" / "validation"
    return folder.is_dir() and any(folder.glob("*.py"))


def shadow(settings: Settings, name: str) -> dict:
    path = settings.registry_dir / "shadow" / f"{name}.json"
    if not path.is_file():
        raise ApiError(404, "not_found", f"no shadow report for {name!r}")
    return json.loads(path.read_text())


def notebook_url(settings: Settings, name: str, reachable: bool) -> dict:
    entry = next((m for m in registry(settings)["candidates"] + [registry(settings)["champion"] or {}]
                  if m and m.get("name") == name), None)
    rel = (entry or {}).get("investigation_notebook") or NOTEBOOK_03
    return {
        "url": f"{settings.jupyter_url.rstrip('/')}/lab/tree/{rel}?token={settings.jupyter_token}",
        "path": rel,
        "exists": (settings.repo_root / rel).is_file(),
        "jupyter_reachable": reachable,
    }


# --- gates --------------------------------------------------------------------

def gate_commands(settings: Settings) -> list[dict]:
    """The `uv run python -m ml.validation.*` steps of model-validation.yml, in order, plus the model-card check."""
    path = settings.workflows_dir / "model-validation.yml"
    gates: list[dict] = []
    if path.is_file():
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            doc = {}
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps", []):
                run = str(step.get("run") or "").strip()
                match = _GATE_MODULE.search(run)
                if match and run.startswith("uv run"):
                    gates.append({"gate": match.group(1), "command": run.splitlines()[0], "step": step.get("name")})
                elif "MODEL_CARD.md" in run:
                    gates.append({"gate": "model_card", "command": "test -f ml/fraud/MODEL_CARD.md", "step": step.get("name")})
    if not gates:  # the contract file is missing -- fall back to the agreed gates
        gates = [
            {"gate": "leakage", "command": "uv run python -m ml.validation.leakage --fail-on-leak", "step": None},
            {"gate": "performance", "command": "uv run python -m ml.validation.performance --min-pr-auc 0.15", "step": None},
            {"gate": "drift", "command": "uv run python -m ml.validation.drift --max-psi 0.25", "step": None},
            {"gate": "fairness", "command": "uv run python -m ml.validation.fairness --report fairness.md", "step": None},
            {"gate": "model_card", "command": "test -f ml/fraud/MODEL_CARD.md", "step": None},
        ]
    return gates


class GateRunner:
    def __init__(self, settings: Settings, bus: EventBus, timeline: Timeline, python: list[str] | None = None,
                 timeout: float = 180.0) -> None:
        self.settings, self.bus, self.timeline, self.timeout = settings, bus, timeline, timeout
        self.python = python          # tests substitute the interpreter for `uv run python`
        self.results: dict[str, list[dict]] = {}
        self._task: asyncio.Task | None = None

    def latest(self, model: str) -> list[dict]:
        return self.results.get(model, [])

    async def start(self, model: str, persona: str = "ds") -> dict:
        if self._task and not self._task.done():
            raise ApiError(409, "gates_running", "a gate run is already in progress")
        gates = gate_commands(self.settings)
        gate_run_id = f"gates_{secrets.token_hex(3)}"
        self.results[model] = [self._event(gate_run_id, model, g, "queued") for g in gates]
        for event in self.results[model]:
            self.bus.publish("gate", event)
        self.timeline.append("gates_run", persona, f"Validation gates run for {model}",
                             detail="the four commands from model-validation.yml, plus the model-card check",
                             refs={"model": model, "gate_run_id": gate_run_id})
        self._task = asyncio.create_task(self._run(gate_run_id, model, gates))
        return {"gate_run_id": gate_run_id, "gates": [{"gate": g["gate"], "command": g["command"]} for g in gates]}

    async def _run(self, gate_run_id: str, model: str, gates: list[dict]) -> None:
        outcomes = []
        for index, gate in enumerate(gates):
            self._set(model, index, self._event(gate_run_id, model, gate, "running"))
            result = await asyncio.to_thread(self._execute, gate)
            self._set(model, index, self._event(gate_run_id, model, gate, **result))
            outcomes.append(result["status"])
            if result["status"] in ("pass", "blocked"):
                self.timeline.append(
                    "gate_passed" if result["status"] == "pass" else "gate_blocked", "system",
                    f"{gate['step'] or gate['gate']}: {'PASS' if result['status'] == 'pass' else 'BLOCKED'}",
                    detail=(result.get("stdout_tail") or "").strip().splitlines()[-1] if result.get("stdout_tail") else None,
                    refs={"model": model, "gate": gate["gate"], "gate_run_id": gate_run_id},
                )

    def _execute(self, gate: dict) -> dict:
        started = time.monotonic()
        if gate["gate"] == "model_card":
            present = (self.settings.repo_root / "ml" / "fraud" / "MODEL_CARD.md").is_file()
            return {"status": "pass" if present else "blocked", "exit_code": 0 if present else 1,
                    "stdout_tail": "ml/fraud/MODEL_CARD.md present" if present else "no model card -- MRM will not review this",
                    "duration_s": 0.0}
        argv = shlex.split(gate["command"])
        if self.python and argv[:3] == ["uv", "run", "python"]:
            argv = [*self.python, *argv[3:]]
        try:
            proc = subprocess.run(argv, cwd=self.settings.repo_root, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return {"status": "error", "exit_code": None, "stdout_tail": f"timed out after {self.timeout:g}s", "duration_s": round(time.monotonic() - started, 1)}
        except OSError as exc:
            return {"status": "error", "exit_code": None, "stdout_tail": str(exc), "duration_s": 0.0}
        output = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
        if proc.returncode != 0 and _NOT_IMPLEMENTED.search(proc.stderr or ""):
            status = "not_implemented"
        else:
            status = "pass" if proc.returncode == 0 else "blocked"
        return {"status": status, "exit_code": proc.returncode, "stdout_tail": output[-1500:],
                "duration_s": round(time.monotonic() - started, 1)}

    def _event(self, gate_run_id: str, model: str, gate: dict, status: str, **extra: object) -> dict:
        return {"gate_run_id": gate_run_id, "model": model, "gate": gate["gate"], "command": gate["command"],
                "status": status, "ts": now_iso(), **extra}

    def _set(self, model: str, index: int, event: dict) -> None:
        self.results[model][index] = event
        self.bus.publish("gate", event)


def proof(settings: Settings, python: list[str] | None = None, timeout: float = 300.0) -> dict:
    """`uv run pytest ml/validation -q -rA`: the gate catching the notebook's definition, as tests."""
    argv = ["uv", "run", "pytest", "ml/validation", "-q", "-rA", "-p", "no:cacheprovider"]
    if python:
        argv = [*python, "-m", "pytest", *argv[3:]]
    try:
        proc = subprocess.run(argv, cwd=settings.repo_root, capture_output=True, text=True, timeout=timeout,
                              env={**__import__("os").environ, "TESSERA_AUDIT_DISABLE": "1"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "tests": [], "output": str(exc)}
    tests = [{"outcome": m.group(1).lower(), "name": m.group(2)} for m in _PYTEST_LINE.finditer(proc.stdout)]
    return {"exit_code": proc.returncode, "tests": tests, "output": (proc.stdout + proc.stderr)[-3000:]}


# --- artifact watcher -----------------------------------------------------------

class ArtifactWatcher:
    """Notices what the data scientist's session leaves behind and puts it on the timeline."""

    def __init__(self, settings: Settings, timeline: Timeline, persona: Callable[[], str], interval: float = 2.0) -> None:
        self.settings, self.timeline, self.persona, self.interval = settings, timeline, persona, interval
        self._seen: dict[str, object] = {}
        self._candidate: str | None = None   # a notebook hash seen once; counts only if seen twice

    def prime(self) -> None:
        self._seen = self._state()

    def _state(self) -> dict[str, object]:
        root = self.settings.repo_root
        nb = root / NOTEBOOK_03
        return {
            "validation": validation_present(self.settings),
            "model_card": (root / "ml" / "fraud" / "MODEL_CARD.md").is_file(),
            "aggregates": (root / "ml" / "features" / "aggregates.py").is_file(),
            # Content, not mtime: a reset regenerates the seed byte-for-byte and must not count as an edit.
            "notebook_hash": hashlib.sha1(nb.read_bytes()).hexdigest() if nb.is_file() else None,
        }

    def scan(self) -> list[str]:
        current = self._state()
        fired = []
        p = self.persona()
        if current["validation"] and not self._seen.get("validation"):
            self.timeline.append("gates_implemented", p, "ml/validation/ implemented",
                                 detail="the four gates model-validation.yml specifies now have code behind them (TESS-2310)",
                                 refs={"path": "ml/validation/"})
            fired.append("gates_implemented")
        if current["model_card"] and not self._seen.get("model_card"):
            self.timeline.append("model_card_added", p, "Model card added", detail="ml/fraud/MODEL_CARD.md",
                                 refs={"path": "ml/fraud/MODEL_CARD.md"})
            fired.append("model_card_added")
        if current["aggregates"] and not self._seen.get("aggregates"):
            self.timeline.append("aggregates_added", p, "Point-in-time feature added",
                                 detail="ml/features/aggregates.py — card_chargeback_rate(df, as_of)",
                                 refs={"path": "ml/features/aggregates.py"})
            fired.append("aggregates_added")
        # Debounced: a poll can land while the file is being rewritten (a reset
        # reseeds it) and read a truncated copy. Only a hash that holds for two
        # consecutive polls is an edit.
        nb_hash, seen_hash = current["notebook_hash"], self._seen.get("notebook_hash")
        if nb_hash and seen_hash and nb_hash != seen_hash:
            if nb_hash == self._candidate:
                self.timeline.append("notebook_updated", p, "Investigation notebook updated",
                                     detail=NOTEBOOK_03, refs={"path": NOTEBOOK_03})
                fired.append("notebook_updated")
                seen_hash = nb_hash
            else:
                self._candidate = nb_hash
        else:
            self._candidate = None
            seen_hash = nb_hash if not seen_hash else seen_hash
        self._seen = {**current, "notebook_hash": seen_hash}
        return fired

    async def run(self) -> None:
        self.prime()
        while True:
            try:
                await asyncio.to_thread(self.scan)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self.interval)
