"""
Tessera Ops Console -- application factory.

    uv run uvicorn services.console.app:create_app --factory --port 8765

One process serves the JSON API under /api, a single SSE stream at
/api/events, and the built frontend from web/dist. State the handlers share
lives on `Console`, reachable as `request.app.state.console`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .audit import AuditTailer
from .bus import EventBus
from .errors import ApiError
from .gitops import Git
from .health import HealthMonitor
from .models import ArtifactWatcher, GateRunner
from .prs import PRWatcher, provider_for
from .runner import Runner
from .settings import Settings
from .timeline import Timeline


class Console:
    """Everything the request handlers share. One per process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.git = Git(settings.repo_root)
        self.bus = EventBus()
        self.timeline = Timeline(settings.events_path, self.bus)
        self.persona = "sre"
        # session_id -> run_id, filled by the runner so audit lines can be attributed.
        self.session_index: dict[str, str] = {}
        self.health = HealthMonitor(self.git, self.bus, settings.health_interval_seconds,
                                    on_recovered=self._recovered)
        self.audit = AuditTailer(settings.audit_path, self.bus, self.timeline, self.resolve_source,
                                 lambda: self.persona, settings.audit_interval_seconds)
        self.prs = provider_for(settings, self.git)
        self.runner = Runner(settings, self.git, self.bus, self.timeline, self.session_index,
                             on_artifacts=lambda: self.watcher.scan())
        self.watcher = PRWatcher(self.prs, self.bus, self.timeline, lambda: self.persona,
                                 self.runner.run_for_branch, settings.poll_interval_seconds)
        self.gates = GateRunner(settings, self.bus, self.timeline, python=settings.gate_python)
        self.artifacts = ArtifactWatcher(settings, self.timeline, lambda: self.persona if self.persona == "ds" else "ds",
                                         settings.poll_interval_seconds)
        self.tasks: list[asyncio.Task] = []

    @property
    def active_run(self):
        return self.runner.active

    # --- cross-cutting helpers ---------------------------------------------
    def resolve_source(self, session_id: str | None) -> tuple[str, str | None]:
        run_id = self.session_index.get(session_id or "")
        return ("run", run_id) if run_id else ("desktop", None)

    def _recovered(self, snap: dict) -> None:
        prod = snap["production"]
        result = prod.get("result", {})
        self.timeline.append(
            "recovered", "system", "Production is healthy again",
            detail=(f"main@{prod.get('sha')}: success {result.get('success_rate', 0):.1%}, "
                    f"p99 {result.get('p99_latency_seconds', 0):.2f}s, utilization {result.get('utilization', 0):.2f}"),
            refs={"sha": prod.get("sha")},
        )

    def incident_status(self, incident_id: str) -> str:
        if self.active_run is not None and getattr(self.active_run, "incident_id", None) == incident_id:
            return "triaging"
        mine = [e for e in self.timeline.load() if (e.get("refs") or {}).get("incident_id") == incident_id]
        if any(e["type"] == "merged" for e in mine):
            current = self.health.current or self.health.refresh()
            return "recovered" if current["production"].get("verdict") == "healthy" else "merged"
        if any(pr.incident_id == incident_id for pr in self.prs.list()) or any(e["type"] == "pr_opened" for e in mine):
            return "pr_open"
        if self.git.branches(f"incident/{incident_id}-*"):
            return "pr_open"
        return "open"

    # --- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        self.settings.tessera_dir.mkdir(parents=True, exist_ok=True)
        self.watcher.prime()
        self.tasks = [asyncio.create_task(self.health.run(), name="health"),
                      asyncio.create_task(self.audit.run(), name="audit"),
                      asyncio.create_task(self.watcher.run(), name="prs"),
                      asyncio.create_task(self.artifacts.run(), name="artifacts")]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.tasks = []


PLACEHOLDER = """<!doctype html><meta charset="utf-8"><title>Tessera Console</title>
<body style="font-family:system-ui;padding:3rem;max-width:40rem">
<h1>Tessera Console API is up</h1>
<p>The frontend has not been built. From the repo root:</p>
<pre>npm --prefix web ci &amp;&amp; npm --prefix web run build</pre>
<p>or run <code>./demo/up.sh</code>, which does that when <code>web/dist</code> is stale.
The API is at <a href="/api/health">/api/health</a>.</p>"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    console = Console(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await console.start()
        try:
            yield
        finally:
            await console.stop()

    app = FastAPI(title="Tessera Ops Console", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.console = console

    from .api import router  # noqa: E402 -- avoid an import cycle at module load

    app.include_router(router, prefix="/api")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail)}},
                            status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": {"code": "validation_error", "message": "invalid request",
                                       "details": exc.errors()}}, status_code=422)

    dist = settings.web_dist
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", f"no such endpoint: /{path}")
        candidate = dist / path
        if path and candidate.is_file() and _inside(candidate, dist):
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(PLACEHOLDER, status_code=503)

    return app


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
