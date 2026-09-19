from services.console.incidents import list_incidents, load_bundle


def test_list_incidents_reads_alert_headers(settings):
    [inc] = list_incidents(settings)
    assert inc["id"] == "INC-4412"
    assert inc["severity"] == "SEV-2"
    assert inc["created_at"] == "2026-09-17T14:11:00Z"


def test_bundle_is_chartable(settings):
    bundle = load_bundle(settings, "INC-4412")
    assert len(bundle["metrics"]) == 71
    assert bundle["metrics"][0]["ts"] == "2026-09-17T13:30:00Z"
    assert set(bundle["metrics"][0]) == {"ts", "fraud_model_rps", "cache_hit_rate", "p99_latency_seconds", "auth_success_rate"}

    assert [d["service"] for d in bundle["deploys"]] == ["payments-api", "kyc-adapter", "risk-gateway", "merchant-portal"]
    risk = bundle["deploys"][2]
    assert risk["started"] == "2026-09-17T14:02:07Z" and risk["revision"]

    kinds = {m["kind"] for m in bundle["markers"]}
    assert kinds == {"deploy", "inflection", "alert"}
    inflection = next(m for m in bundle["markers"] if m["kind"] == "inflection")
    assert inflection["ts"] == "2026-09-17T14:03:00Z"
    alert = next(m for m in bundle["markers"] if m["kind"] == "alert")
    assert alert["ts"] == "2026-09-17T14:11:00Z"
    assert bundle["markers"] == sorted(bundle["markers"], key=lambda m: m["ts"])

    assert len(bundle["logs"]) == 79
    assert len(bundle["traces"]["spans"]) == 6
    assert {f["name"] for f in bundle["files"]} >= {"alert.json", "metrics.csv", "logs.jsonl", "traces.json", "deploys.txt"}


def test_missing_incident_is_none(settings):
    assert load_bundle(settings, "INC-0000") is None
