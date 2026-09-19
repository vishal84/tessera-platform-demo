from pathlib import Path

from services.console.bus import EventBus
from services.console.prs import LocalPRProvider, PRWatcher, parse_pr_file
from services.console.gitops import Git
from services.console.tests.conftest import git
from services.console.tests.test_health import write_fixed_config
from services.console.timeline import Timeline

BRANCH = "incident/INC-4412-fix"
PR_TEXT = """---
title: "fix(risk): restore the cache TTL"
branch: incident/INC-4412-fix
base: main
---
## Summary

Restores the TTL.
"""


def make_pr(repo: Path, settings) -> None:
    git(repo, "checkout", "-q", "-b", BRANCH)
    write_fixed_config(repo)
    git(repo, "commit", "-q", "-am", "fix(risk): restore cache ttl")
    settings.prs_dir.mkdir(parents=True, exist_ok=True)
    (settings.prs_dir / "incident__INC-4412-fix.md").write_text(PR_TEXT)
    git(repo, "checkout", "-q", "main")


def test_front_matter_parsing():
    meta, body = parse_pr_file(PR_TEXT)
    assert meta["title"].startswith("fix(risk)") and meta["base"] == "main"
    assert body.startswith("## Summary")
    assert parse_pr_file("no front matter") == ({}, "no front matter")


def test_local_provider_lists_diffs_reviews_and_merges(client, demo_repo, settings):
    make_pr(demo_repo, settings)
    [pr] = client.get("/api/prs").json()
    assert pr["id"] == BRANCH and pr["state"] == "open" and pr["incident_id"] == "INC-4412"
    assert pr["title"] == "fix(risk): restore the cache TTL" and pr["body_md"].startswith("## Summary")
    assert [c["subject"] for c in pr["commits"]] == ["fix(risk): restore cache ttl"]
    assert [f["path"] for f in pr["files"]] == ["services/risk_gateway/config.py"]
    assert pr["path"] == ".tessera/prs/incident__INC-4412-fix.md"

    assert client.get(f"/api/prs/{BRANCH}").json()["id"] == BRANCH
    diff = client.get(f"/api/prs/{BRANCH}/diff").json()
    assert "+CACHE_TTL_SECONDS = 300" in diff["diff"] and diff["stat"][0]["path"].endswith("config.py")

    review = client.post(f"/api/prs/{BRANCH}/review-request", json={"persona": "swe"}).json()
    assert BRANCH in review["prompt"] and ".tessera/prs/incident__INC-4412-fix.md" in review["prompt"]
    assert client.get("/api/health").json()["persona"] == "swe"

    assert client.get("/api/gateway/health").json()["production"]["verdict"] == "degraded"
    merged = client.post(f"/api/prs/{BRANCH}/merge", json={"persona": "swe"})
    assert merged.status_code == 200, merged.text
    assert merged.json()["production"]["verdict"] == "healthy"
    assert client.get(f"/api/prs/{BRANCH}").json()["state"] == "merged"
    types = [e["type"] for e in client.get("/api/timeline").json()]
    assert types[-2:] == ["merged", "recovered"], types
    assert client.get("/api/incidents").json()[0]["status"] == "recovered"
    assert client.post(f"/api/prs/{BRANCH}/merge", json={}).status_code == 409
    assert client.get("/api/prs/nope/diff").status_code == 404


def test_merge_refuses_a_dirty_tree(client, demo_repo, settings):
    make_pr(demo_repo, settings)
    (demo_repo / "README.md").write_text("uncommitted\n")
    response = client.post(f"/api/prs/{BRANCH}/merge", json={})
    assert response.status_code == 412 and response.json()["error"]["code"] == "dirty_tree"


def test_watcher_reports_opened_updated_and_merged(demo_repo, settings):
    bus = EventBus()
    timeline = Timeline(settings.events_path, bus)
    g = Git(demo_repo)
    provider = LocalPRProvider(settings, g)
    watcher = PRWatcher(provider, bus, timeline, persona=lambda: "swe", run_for_branch=lambda b: "run_9")
    watcher.prime()
    assert watcher.scan() == []

    make_pr(demo_repo, settings)
    [new] = watcher.scan()
    assert new.id == BRANCH
    assert [e["type"] for e in bus.history("pr")] == ["pr_opened"]
    assert timeline.load()[-1]["refs"]["run_id"] == "run_9"

    git(demo_repo, "checkout", "-q", BRANCH)
    (demo_repo / "docs.md").write_text("runbook note\n")
    git(demo_repo, "add", "docs.md")
    git(demo_repo, "commit", "-q", "-m", "docs: runbook note")
    git(demo_repo, "checkout", "-q", "main")
    assert watcher.scan() == []
    assert bus.history("pr")[-1]["type"] == "pr_updated"
    updated = timeline.load()[-1]
    assert updated["type"] == "pr_updated" and updated["persona"] == "swe" and "runbook note" in updated["title"]

    provider.merge(BRANCH)
    watcher.scan()
    assert bus.history("pr")[-1]["type"] == "pr_merged"
    assert timeline.load()[-1]["type"] == "merged" and timeline.load()[-1]["persona"] == "system"
    assert watcher.scan() == [] and bus.history("pr")[-1]["type"] == "pr_merged", "no duplicate events"
