"""
Gateway health, computed from configuration rather than observed.

Production is whatever `main` says. That distinction matters: a headless triage
run edits `services/risk_gateway/config.py` on a branch in the same working
tree, so a tile that read the working tree would turn green while the fix was
still an unreviewed diff. The working-tree number is shown too, labelled as
such, because watching it move during a run is part of the story.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict
from pathlib import Path

from services.risk_gateway.simulation import GatewayConfig, simulate

from .bus import EventBus, now_iso
from .gitops import Git

CONFIG_PATH = "services/risk_gateway/config.py"
CONFIG_KEYS = (
    "CACHE_TTL_SECONDS", "REQUEST_TIMEOUT_SECONDS", "RETRY_ATTEMPTS",
    "RETRY_BACKOFF_BASE_SECONDS", "RETRY_JITTER", "MAX_CONNECTIONS",
    "CIRCUIT_BREAKER_ENABLED", "CIRCUIT_BREAKER_ERROR_THRESHOLD", "CIRCUIT_BREAKER_RESET_SECONDS",
)
SLO = {"success_rate": 0.995, "p99_seconds": 1.0}


def parse_config(source: str) -> dict[str, object]:
    """Pull the module-level constants out of config.py without importing it."""
    values: dict[str, object] = {}
    for node in ast.parse(source).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id in CONFIG_KEYS:
                values[target.id] = ast.literal_eval(value)
    missing = [key for key in CONFIG_KEYS[:7] if key not in values]
    if missing:
        raise ValueError(f"config.py is missing {missing}")
    return values


def verdict(result: dict) -> str:
    healthy = (
        result["utilization"] < 1.0
        and result["success_rate"] >= SLO["success_rate"]
        and result["p99_latency_seconds"] <= SLO["p99_seconds"]
    )
    return "healthy" if healthy else "degraded"


def assess(config: dict[str, object]) -> dict:
    gateway = GatewayConfig(
        cache_ttl_seconds=float(config["CACHE_TTL_SECONDS"]),
        retry_attempts=int(config["RETRY_ATTEMPTS"]),
        backoff_base_seconds=float(config["RETRY_BACKOFF_BASE_SECONDS"]),
        jitter=bool(config["RETRY_JITTER"]),
        request_timeout_seconds=config["REQUEST_TIMEOUT_SECONDS"],
        circuit_breaker_enabled=bool(config["CIRCUIT_BREAKER_ENABLED"]),
    )
    result = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(simulate(gateway)).items()}
    return {"config": config, "result": result, "verdict": verdict(result)}


def _from_source(ref: str, sha: str | None, source: str | None) -> dict:
    if source is None:
        return {"ref": ref, "sha": sha, "verdict": "unknown", "error": f"{CONFIG_PATH} not found at {ref}"}
    try:
        return {"ref": ref, "sha": sha, **assess(parse_config(source))}
    except (ValueError, SyntaxError, KeyError, TypeError) as exc:
        return {"ref": ref, "sha": sha, "verdict": "unknown", "error": str(exc)}


def snapshot(git: Git) -> dict:
    production = _from_source("main", git.short("main"), git.show("main", CONFIG_PATH))
    tree_path = git.repo / CONFIG_PATH
    working = _from_source(
        "working-tree", git.short("HEAD"),
        tree_path.read_text() if tree_path.exists() else None,
    )
    working["branch"] = git.current_branch()
    return {"production": production, "working_tree": working, "slo": SLO, "checked_at": now_iso()}


class HealthMonitor:
    """Re-evaluates health every few seconds and publishes only on change."""

    def __init__(self, git: Git, bus: EventBus, interval: float = 5.0, on_recovered=None) -> None:
        self.git, self.bus, self.interval, self.on_recovered = git, bus, interval, on_recovered
        self.current: dict | None = None

    def refresh(self) -> dict:
        fresh = snapshot(self.git)
        previous = self.current
        changed = previous is None or _comparable(previous) != _comparable(fresh)
        self.current = fresh
        if changed:
            self.bus.publish("health", fresh)
            if (previous and previous["production"].get("verdict") == "degraded"
                    and fresh["production"].get("verdict") == "healthy" and self.on_recovered):
                self.on_recovered(fresh)
        return fresh

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.refresh)
            except Exception:  # noqa: BLE001 -- a poller must not die on a transient git error
                pass
            await asyncio.sleep(self.interval)


def _comparable(snap: dict) -> dict:
    return {k: v for k, v in snap.items() if k != "checked_at"}
