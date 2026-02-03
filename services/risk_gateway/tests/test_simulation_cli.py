"""
The simulation's command line is part of the runbook and the ops console reads
its --json form, so both outputs are pinned here.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.risk_gateway.simulation import config_from_module, simulate

REPO = Path(__file__).resolve().parents[3]


def _run(*args: str) -> str:
    return subprocess.run(
        [sys.executable, "-m", "services.risk_gateway.simulation", *args],
        capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout


def test_default_output_is_the_one_line_summary():
    out = _run()
    assert out.startswith("live config :")
    assert out.count("\n") == 1


def test_json_output_round_trips_config_and_result():
    payload = json.loads(_run("--json"))
    assert set(payload) == {"config", "result"}
    assert set(payload["config"]) == {
        "cache_ttl_seconds", "retry_attempts", "backoff_base_seconds",
        "jitter", "request_timeout_seconds", "circuit_breaker_enabled",
    }
    live = simulate(config_from_module())
    assert payload["result"]["utilization"] == pytest.approx(live.utilization)
    assert payload["result"]["success_rate"] == pytest.approx(live.success_rate)
    assert payload["result"]["saturated"] == live.saturated
