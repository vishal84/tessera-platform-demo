"""
Console configuration.

Everything hangs off the repository root. Runtime state lives under
.tessera/ (gitignored) and nothing there is a source of truth: the audit trail
is written by the guardrail hooks, run recordings by the runner, and local pull
requests by a headless Claude session following the console's instructions.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    repo_root: Path = DEFAULT_REPO_ROOT
    console_port: int = 8765
    jupyter_url: str = "http://localhost:8888"
    jupyter_token: str = "tessera"
    claude_bin: str = "claude"
    # Pins the model a run (and so a recording) is produced with, e.g.
    # claude-fable-5-1. None leaves the choice to the CLI.
    claude_model: str | None = None
    max_turns: int = 40
    max_budget_usd: float = 20.0
    # None means "ask the track": the incident beat finishes inside 15 minutes,
    # the model beat does not. A value here overrides every track.
    run_timeout_seconds: float | None = None
    poll_interval_seconds: float = 2.0
    health_interval_seconds: float = 5.0
    audit_interval_seconds: float = 0.5
    # "local" keeps pull requests in .tessera/prs/ even when a remote exists.
    # Anything else uses GitHub when a remote and `gh` auth are available.
    pr_provider: str = "auto"
    # Tests substitute an interpreter for `uv run python` in gate commands.
    gate_python: tuple[str, ...] | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        jupyter_port = env.get("TESSERA_JUPYTER_PORT", "8888")
        return cls(
            repo_root=Path(env.get("TESSERA_REPO_ROOT") or DEFAULT_REPO_ROOT).resolve(),
            console_port=int(env.get("TESSERA_CONSOLE_PORT", "8765")),
            jupyter_url=env.get("TESSERA_JUPYTER_URL", f"http://localhost:{jupyter_port}"),
            jupyter_token=env.get("TESSERA_JUPYTER_TOKEN", "tessera"),
            claude_bin=env.get("TESSERA_CLAUDE_BIN") or shutil.which("claude") or "claude",
            claude_model=env.get("TESSERA_CLAUDE_MODEL") or None,
            max_budget_usd=float(env.get("TESSERA_MAX_BUDGET_USD", "20")),
            pr_provider=env.get("TESSERA_PR_PROVIDER", "auto").strip().lower() or "auto",
            run_timeout_seconds=(float(raw_timeout) if (raw_timeout := env.get("TESSERA_RUN_TIMEOUT_SECONDS")) else None),
        )

    # --- runtime state (gitignored) -------------------------------------
    @property
    def tessera_dir(self) -> Path:
        return self.repo_root / ".tessera"

    @property
    def audit_path(self) -> Path:
        return self.tessera_dir / "audit.jsonl"

    @property
    def events_path(self) -> Path:
        return self.tessera_dir / "events.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.tessera_dir / "runs"

    @property
    def prs_dir(self) -> Path:
        return self.tessera_dir / "prs"

    @property
    def lock_path(self) -> Path:
        return self.tessera_dir / "run.lock"

    # --- repository content ----------------------------------------------
    @property
    def recordings_dir(self) -> Path:
        return self.repo_root / "demo" / "recordings"

    @property
    def web_dist(self) -> Path:
        return self.repo_root / "web" / "dist"

    @property
    def incidents_dir(self) -> Path:
        return self.repo_root / "ops" / "incidents"

    @property
    def registry_dir(self) -> Path:
        return self.repo_root / "ml" / "registry"

    @property
    def claude_settings(self) -> Path:
        return self.repo_root / ".claude" / "settings.json"

    @property
    def hooks_dir(self) -> Path:
        return self.repo_root / ".claude" / "hooks"

    @property
    def workflows_dir(self) -> Path:
        return self.repo_root / ".github" / "workflows"
