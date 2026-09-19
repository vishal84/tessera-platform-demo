"""Loads an evidence bundle under ops/incidents/<id>/ into JSON the UI can chart."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .health import SLO
from .settings import Settings

METRIC_COLUMNS = ("fraud_model_rps", "cache_hit_rate", "p99_latency_seconds", "auth_success_rate")


def list_incidents(settings: Settings) -> list[dict]:
    incidents = []
    if not settings.incidents_dir.exists():
        return incidents
    for folder in sorted(settings.incidents_dir.iterdir()):
        alert = folder / "alert.json"
        if alert.exists():
            data = json.loads(alert.read_text())
            incidents.append({
                "id": data.get("incident_id", folder.name),
                "severity": data.get("severity"),
                "service": data.get("service"),
                "title": data.get("title"),
                "created_at": data.get("created_at"),
            })
    return incidents


def parse_deploys(text: str, day: str) -> list[dict]:
    deploys = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 5:
            continue
        service, started, finished, revision, deployed_by = parts[:5]
        deploys.append({
            "service": service, "started": f"{day}T{started}Z", "finished": f"{day}T{finished}Z",
            "revision": revision, "deployed_by": deployed_by,
        })
    return deploys


def parse_metrics(text: str) -> list[dict]:
    rows = []
    for row in csv.DictReader(text.splitlines()):
        parsed = {"ts": row["timestamp"]}
        for column in METRIC_COLUMNS:
            parsed[column] = float(row[column])
        rows.append(parsed)
    return rows


def markers(alert: dict, metrics: list[dict], deploys: list[dict]) -> list[dict]:
    out = [{"ts": d["started"], "kind": "deploy", "label": f"{d['service']} {d['revision']}"} for d in deploys]
    inflection = next((m for m in metrics if m["p99_latency_seconds"] > SLO["p99_seconds"]), None)
    if inflection:
        out.append({"ts": inflection["ts"], "kind": "inflection", "label": "p99 crosses SLO"})
    if alert.get("created_at"):
        out.append({"ts": alert["created_at"], "kind": "alert", "label": f"{alert.get('severity', '')} {alert.get('incident_id', '')}".strip()})
    return sorted(out, key=lambda m: m["ts"])


def load_bundle(settings: Settings, incident_id: str) -> dict | None:
    folder = settings.incidents_dir / incident_id
    if not (folder / "alert.json").exists():
        return None
    alert = json.loads((folder / "alert.json").read_text())
    day = alert.get("created_at", "")[:10]
    metrics = parse_metrics(_read(folder / "metrics.csv"))
    deploys = parse_deploys(_read(folder / "deploys.txt"), day)
    logs = [json.loads(line) for line in _read(folder / "logs.jsonl").splitlines() if line.strip()]
    traces = json.loads(_read(folder / "traces.json") or "{}")
    files = [{"name": p.name, "bytes": p.stat().st_size, "lines": _read(p).count("\n")}
             for p in sorted(folder.iterdir()) if p.is_file()]
    return {
        "id": alert.get("incident_id", incident_id),
        "alert": alert,
        "metrics": metrics,
        "deploys": deploys,
        "logs": logs,
        "traces": traces,
        "markers": markers(alert, metrics, deploys),
        "files": files,
        "readme": _read(folder / "README.md"),
    }


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""
