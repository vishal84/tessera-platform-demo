"""
A throwaway git repository with just enough of the platform in it: the seeded
risk-gateway config on `main`, the INC-4412 evidence bundle, the guardrail
hooks and settings, and the workflows the console mirrors.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.console.app import create_app
from services.console.settings import Settings

REAL_REPO = Path(__file__).resolve().parents[3]
FAKE_CLAUDE = Path(__file__).resolve().parent / "fixtures" / "fake_claude.py"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Tessera CI", "GIT_AUTHOR_EMAIL": "ci@tessera.test",
    "GIT_COMMITTER_NAME": "Tessera CI", "GIT_COMMITTER_EMAIL": "ci@tessera.test",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout


COPY = [
    "ops/incidents/INC-4412",
    "ops/slo.yaml",
    ".claude/settings.json",
    ".claude/hooks",
    ".github/workflows",
]

# The risk-gateway config as it stood at 14:02 UTC on 2026-09-17, pinned rather
# than copied out of the working tree. The console's whole premise is that a
# triage run edits this file on a branch in the same checkout, so a fixture that
# read the live file would stop representing the incident the moment anyone
# fixed it -- which is what happened in INC-4412's own remediation.
SEEDED_CONFIG = '''"""Risk gateway tuning. Values here are on the synchronous authorization path."""

# Fraud model response cache. Scoring the same card+amount repeatedly within a
# short window produces the same decision, so caching absorbs most of the load.
CACHE_TTL_SECONDS = 0

# Upstream call behaviour.
REQUEST_TIMEOUT_SECONDS = None
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 0.0
RETRY_JITTER = False

# Connection pool to the fraud model service.
MAX_CONNECTIONS = 512

# Circuit breaker. Disabled -- never got prioritised.
CIRCUIT_BREAKER_ENABLED = False
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.5
CIRCUIT_BREAKER_RESET_SECONDS = 30
'''


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel in COPY:
        src, dst = REAL_REPO / rel, repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    seeded = repo / "services/risk_gateway/config.py"
    seeded.parent.mkdir(parents=True, exist_ok=True)
    seeded.write_text(SEEDED_CONFIG)
    (repo / "README.md").write_text("Tessera demo fixture\n")
    (repo / ".gitignore").write_text(".tessera/\n__pycache__/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: platform scaffold")
    git(repo, "tag", "demo-base")
    return repo


@pytest.fixture
def settings(demo_repo: Path) -> Settings:
    return Settings(
        repo_root=demo_repo, claude_bin=str(FAKE_CLAUDE),
        health_interval_seconds=0.05, audit_interval_seconds=0.05, poll_interval_seconds=0.05,
        run_timeout_seconds=20,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    """No lifespan: pollers stay off, handlers are exercised directly."""
    return TestClient(app)


@pytest.fixture
def live_client(app):
    """With lifespan: the health monitor and audit tailer run in the background."""
    with TestClient(app) as tc:
        yield tc
