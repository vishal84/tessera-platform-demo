#!/usr/bin/env python3
"""
Generate the INC-4412 evidence bundle.

Everything is derived from the capacity model in
services/risk_gateway/simulation.py, so the telemetry is internally
consistent: the latency curve, the request-rate curve and the success-rate
curve all come from the same simulation, and they all inflect at the deploy.

Re-runnable, deterministic. Called by demo/reset-demo.sh.
"""

import json
import math
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.risk_gateway.simulation import GatewayConfig, simulate  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "ops" / "incidents" / "INC-4412"
REPO = Path(__file__).resolve().parents[1]
RNG = random.Random(4412)

DAY = datetime(2026, 9, 17, tzinfo=timezone.utc)
WINDOW_START = DAY.replace(hour=13, minute=30)
DEPLOY_AT = DAY.replace(hour=14, minute=2)
ALERT_AT = DAY.replace(hour=14, minute=11)
WINDOW_END = DAY.replace(hour=14, minute=40)

def risk_gateway_revision() -> str:
    """
    Resolve the short SHA that risk-gateway was running after the 14:02 deploy.

    A deploy ships whatever is at HEAD, which here is the *last* commit of the
    day -- a docstring change, not the one that caused the incident. That is
    deliberate. The deploy record and the config-reload log both name this
    revision, so an investigator who stops at "what did we deploy" finds a
    docstring and has to widen to the full set of commits the deploy carried.
    """
    try:
        sha = subprocess.run(
            ["git", "log", "--format=%h", "-1", "--grep=note fail-closed semantics"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return sha or "<SHA_RISK>"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "<SHA_RISK>"


SHA_RISK = risk_gateway_revision()

HEALTHY = GatewayConfig(300, 3, 0.0, False, None, False)
BROKEN = GatewayConfig(0, 3, 0.0, False, None, False)


def jitter(value: float, pct: float = 0.04) -> float:
    return value * (1 + RNG.uniform(-pct, pct))


def ramp(minutes_since_deploy: float) -> float:
    """Saturation is not instant -- the queue takes a few minutes to build."""
    if minutes_since_deploy < 0:
        return 0.0
    return 1 - math.exp(-minutes_since_deploy / 2.5)


def write_metrics() -> None:
    healthy, broken = simulate(HEALTHY), simulate(BROKEN)
    rows = ["timestamp,fraud_model_rps,cache_hit_rate,p99_latency_seconds,auth_success_rate"]

    t = WINDOW_START
    while t <= WINDOW_END:
        f = ramp((t - DEPLOY_AT).total_seconds() / 60)
        rps = healthy.offered_rps + f * (broken.offered_rps - healthy.offered_rps)
        hit = healthy.cache_hit_rate * (1 - f)
        p99 = healthy.p99_latency_seconds + f * (broken.p99_latency_seconds - healthy.p99_latency_seconds)
        ok = 0.9993 + f * (broken.success_rate - 0.9993)

        rows.append(
            f"{t.isoformat().replace('+00:00','Z')},{jitter(rps):.1f},"
            f"{max(0.0, jitter(hit, 0.02)):.3f},{jitter(p99):.2f},{min(1.0, jitter(ok, 0.01)):.4f}"
        )
        t += timedelta(minutes=1)

    (OUT / "metrics.csv").write_text("\n".join(rows) + "\n")


def write_alert() -> None:
    alert = {
        "incident_id": "INC-4412",
        "created_at": ALERT_AT.isoformat().replace("+00:00", "Z"),
        "severity": "SEV-2",
        "service": "risk-gateway",
        "title": "Authorization success rate below SLO / p99 latency breach",
        "source": "datadog-monitor-8841",
        "triggered_conditions": [
            {
                "monitor": "payments.authorization.success_rate",
                "slo_target": 0.995,
                "observed": 0.708,
                "window": "5m",
            },
            {
                "monitor": "risk_gateway.fraud_model.p99_latency",
                "threshold_seconds": 1.0,
                "observed_seconds": 8.47,
                "window": "5m",
                "note": "p99 pinned at the 8.5s edge budget -- callers are timing out, not slow",
            },
        ],
        "impacted": {
            "declined_authorizations_estimated": 41_300,
            "merchants_affected": 2_184,
            "customer_reports": 63,
        },
        "runbook": "ops/runbooks/risk-gateway.md",
        "dashboards": ["https://datadog.tessera.test/d/risk-gateway-overview"],
    }
    (OUT / "alert.json").write_text(json.dumps(alert, indent=2) + "\n")


def write_deploys() -> None:
    lines = [
        "# Deploy timeline, 2026-09-17 UTC (from ArgoCD)",
        "#",
        "# service          started   finished  revision   deployed_by",
        "  payments-api     13:04:11  13:07:52  a19c4f2    ci-bot",
        "  kyc-adapter      13:41:03  13:43:19  7e2b810    ci-bot",
        f"  risk-gateway     14:02:07  14:05:38  {SHA_RISK:<9}  ci-bot",
        "  merchant-portal  14:19:55  14:24:02  cc90a17    ci-bot",
    ]
    (OUT / "deploys.txt").write_text("\n".join(lines) + "\n")


def write_logs() -> None:
    lines = []

    def emit(ts, level, event, **fields):
        lines.append(
            json.dumps(
                {
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "level": level,
                    "service": "risk-gateway",
                    "event": event,
                    **fields,
                }
            )
        )

    t = DEPLOY_AT - timedelta(minutes=4)
    for _ in range(6):
        emit(t, "INFO", "fraud_score_served", cache="hit", latency_ms=round(jitter(3), 1))
        emit(t + timedelta(seconds=12), "INFO", "fraud_score_served",
             cache="miss", latency_ms=round(jitter(121), 1))
        t += timedelta(seconds=40)

    # Deliberately does NOT enumerate what changed -- the deploy marker links
    # to a revision, and finding what that revision did is the triage work.
    emit(DEPLOY_AT, "INFO", "config_reloaded", revision=SHA_RISK)

    t = DEPLOY_AT + timedelta(seconds=30)
    for i in range(14):
        emit(t, "INFO", "fraud_score_served", cache="miss",
             latency_ms=round(jitter(180 + i * 240), 1))
        if i > 3:
            for attempt in range(4):
                emit(
                    t + timedelta(milliseconds=200 * attempt),
                    "WARN",
                    "fraud_model_attempt_failed",
                    attempt=attempt,
                    error="read timeout: no timeout configured, edge budget exhausted",
                    elapsed_ms=round(jitter(2100 + attempt * 60), 1),
                )
            emit(t + timedelta(milliseconds=900), "ERROR", "fraud_model_exhausted",
                 attempts=4, decision="decline", reason="fail_closed")
        t += timedelta(seconds=45)

    emit(ALERT_AT, "ERROR", "connection_pool_saturated",
         in_use=512, max_connections=512, queued=3_118)
    emit(ALERT_AT + timedelta(seconds=5), "ERROR", "authorization_declined",
         reason="risk_unavailable", count_last_60s=4_812)

    (OUT / "logs.jsonl").write_text("\n".join(lines) + "\n")


def write_traces() -> None:
    base = ALERT_AT - timedelta(minutes=2)
    spans = [
        {"span_id": "s0", "parent": None, "name": "POST /v1/authorizations",
         "service": "payments-api", "start_ms": 0, "duration_ms": 8501,
         "status": "error", "attributes": {"http.status_code": 504}},
        {"span_id": "s1", "parent": "s0", "name": "risk_gateway.score",
         "service": "risk-gateway", "start_ms": 4, "duration_ms": 8492,
         "status": "error",
         "attributes": {"cache.hit": False, "retry.attempts": 4}},
    ]
    start = 6
    for i in range(4):
        spans.append({
            "span_id": f"s1-{i}", "parent": "s1",
            "name": f"http POST fraud-model/v2/score (attempt {i})",
            "service": "fraud-model", "start_ms": start, "duration_ms": 2120 + i * 5,
            "status": "error",
            "attributes": {
                "http.timeout_seconds": None,
                "retry.backoff_ms": 0,
                "queue.wait_ms": 2080 + i * 5,
                "error": "deadline exceeded at caller",
            },
        })
        start += 2122 + i * 5

    (OUT / "traces.json").write_text(
        json.dumps(
            {
                "trace_id": "4412a9c0e1f2b3d4",
                "captured_at": base.isoformat().replace("+00:00", "Z"),
                "note": "Representative slow authorization sampled during the incident.",
                "spans": spans,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write_metrics()
    write_alert()
    write_deploys()
    write_logs()
    write_traces()
    print(f"wrote evidence bundle to {OUT}")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:<16} {f.stat().st_size:>7,} bytes")
