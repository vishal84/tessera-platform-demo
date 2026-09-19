from pathlib import Path

from services.console.bus import EventBus
from services.console.gitops import Git
from services.console.health import HealthMonitor, assess, parse_config, snapshot
from services.console.tests.conftest import REAL_REPO, git

FIXED = {
    "CACHE_TTL_SECONDS": 300, "REQUEST_TIMEOUT_SECONDS": 1.0, "RETRY_ATTEMPTS": 2,
    "RETRY_BACKOFF_BASE_SECONDS": 0.05, "RETRY_JITTER": True, "MAX_CONNECTIONS": 256,
    "CIRCUIT_BREAKER_ENABLED": True, "CIRCUIT_BREAKER_ERROR_THRESHOLD": 0.5,
    "CIRCUIT_BREAKER_RESET_SECONDS": 30,
}


def write_fixed_config(repo: Path) -> None:
    (repo / "services/risk_gateway/config.py").write_text(
        "\n".join(f"{k} = {v!r}" for k, v in FIXED.items()) + "\n")


def test_parse_config_reads_the_seeded_constants_without_importing():
    config = parse_config((REAL_REPO / "services/risk_gateway/config.py").read_text())
    assert config["CACHE_TTL_SECONDS"] == 0
    assert config["REQUEST_TIMEOUT_SECONDS"] is None
    assert config["CIRCUIT_BREAKER_ENABLED"] is False
    assert config["MAX_CONNECTIONS"] == 512


def test_assess_seeded_is_degraded_and_fixed_is_healthy():
    seeded = assess(parse_config((REAL_REPO / "services/risk_gateway/config.py").read_text()))
    assert seeded["verdict"] == "degraded"
    assert seeded["result"]["utilization"] > 7
    fixed = assess(FIXED)
    assert fixed["verdict"] == "healthy"
    assert fixed["result"]["success_rate"] >= 0.995


def test_production_comes_from_main_not_the_working_tree(demo_repo: Path):
    g = Git(demo_repo)
    before = snapshot(g)
    assert before["production"]["verdict"] == "degraded"
    assert before["working_tree"]["verdict"] == "degraded"

    git(demo_repo, "checkout", "-q", "-b", "incident/INC-4412-cache-ttl")
    write_fixed_config(demo_repo)
    after = snapshot(g)
    assert after["production"]["verdict"] == "degraded", "main has not moved"
    assert after["working_tree"]["verdict"] == "healthy"
    assert after["working_tree"]["branch"] == "incident/INC-4412-cache-ttl"


def test_monitor_publishes_on_change_only_and_reports_recovery(demo_repo: Path):
    bus = EventBus()
    recovered = []
    monitor = HealthMonitor(Git(demo_repo), bus, on_recovered=recovered.append)
    monitor.refresh()
    monitor.refresh()
    assert len(bus.history("health")) == 1, "unchanged health is not re-published"

    write_fixed_config(demo_repo)
    git(demo_repo, "commit", "-q", "-am", "fix(risk): restore cache ttl")
    snap = monitor.refresh()
    assert snap["production"]["verdict"] == "healthy"
    assert len(bus.history("health")) == 2
    assert len(recovered) == 1
