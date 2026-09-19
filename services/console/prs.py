"""
Pull requests with or without a forge.

A headless run "opens a PR" by writing `.tessera/prs/<branch>.md` (front-matter
+ body) after committing on its branch. The local provider turns that file plus
git into a PR view. When a remote and `gh` auth exist the GitHub provider is
used instead, unless TESSERA_PR_PROVIDER pins the local one -- see
`use_local_prs` for why the demo does exactly that.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .bus import EventBus
from .errors import ApiError
from .gitops import Git, GitError
from .settings import Settings
from .timeline import Timeline

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_INCIDENT = re.compile(r"(INC-\d+)")
_TICKET = re.compile(r"(TESS-\d+)")
# Branch namespaces a pull request can live in: the SRE beat and the DS beat.
BRANCH_PREFIXES = ("incident/", "ml/")


@dataclass
class PullRequest:
    id: str
    provider: str
    title: str
    branch: str
    base: str = "main"
    state: str = "open"
    number: int | None = None
    url: str | None = None
    created_at: str | None = None
    head_sha: str | None = None
    body_md: str = ""
    commits: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    path: str | None = None

    @property
    def incident_id(self) -> str | None:
        match = _INCIDENT.search(self.branch)
        return match.group(1) if match else None

    @property
    def ticket(self) -> str | None:
        """The DS beat names its branches for the ticket, not an incident."""
        match = _TICKET.search(self.branch)
        return match.group(1) if match else None

    @property
    def track(self) -> str:
        return "model" if self.branch.startswith("ml/") else "incident"

    def as_dict(self) -> dict:
        return {**asdict(self), "incident_id": self.incident_id,
                "ticket": self.ticket, "track": self.track}


def pr_filename(branch: str) -> str:
    return branch.replace("/", "__") + ".md"


def parse_pr_file(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), match.group(2)


class LocalPRProvider:
    name = "local"

    def __init__(self, settings: Settings, git: Git) -> None:
        self.settings, self.git = settings, git

    def list(self) -> list[PullRequest]:
        prs = []
        if self.settings.prs_dir.exists():
            for path in sorted(self.settings.prs_dir.glob("*.md")):
                pr = self._load(path)
                if pr:
                    prs.append(pr)
        return prs

    def get(self, pr_id: str) -> PullRequest:
        for pr in self.list():
            if pr.id == pr_id:
                return pr
        raise ApiError(404, "not_found", f"no pull request {pr_id!r}")

    def diff(self, pr_id: str) -> dict:
        pr = self.get(pr_id)
        if not self.git.branch_exists(pr.branch):
            return {"diff": "", "stat": []}
        return {"diff": self.git.diff(pr.base, pr.branch), "stat": self.git.diff_stat(pr.base, pr.branch)}

    def merge(self, pr_id: str) -> str:
        pr = self.get(pr_id)
        if pr.state != "open":
            raise ApiError(409, "already_merged", f"{pr_id} is already {pr.state}")
        if not self.git.branch_exists(pr.branch):
            raise ApiError(412, "no_branch", f"branch {pr.branch} does not exist locally")
        if not self.git.is_clean(include_untracked=False):
            raise ApiError(412, "dirty_tree", "the working tree has uncommitted changes; commit or discard them first",
                           details=[f"{code} {path}" for code, path in self.git.status() if code != "??"])
        try:
            self.git.checkout(pr.base)
            return self.git.merge_no_ff(pr.branch, f"Merge {pr.branch}: {pr.title}")
        except GitError as exc:
            raise ApiError(500, "merge_failed", str(exc)) from exc

    def _load(self, path: Path) -> PullRequest | None:
        try:
            meta, body = parse_pr_file(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        branch = str(meta.get("branch") or path.stem.replace("__", "/"))
        base = str(meta.get("base") or "main")
        title = str(meta.get("title") or _first_heading(body) or path.stem)
        exists = self.git.branch_exists(branch)
        merged = exists and branch != base and self.git.merge_base_is_ancestor(branch, base)
        commits = [c.as_dict() for c in self.git.log(f"{base}..{branch}")] if exists else []
        return PullRequest(
            id=branch, provider=self.name, title=title, branch=branch, base=base,
            state="merged" if merged else "open",
            created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            head_sha=self.git.short(branch) if exists else None,
            body_md=body.strip(), commits=commits,
            files=self.git.diff_stat(base, branch) if exists else [],
            path=str(path.relative_to(self.settings.repo_root)),
        )


class GitHubPRProvider:
    """Thin wrapper over `gh`. Only reachable when a remote and gh auth exist."""

    name = "github"

    def __init__(self, settings: Settings, git: Git) -> None:
        self.settings, self.git = settings, git

    def _gh(self, *args: str) -> str:
        proc = subprocess.run(["gh", *args], cwd=self.settings.repo_root, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise ApiError(502, "gh_failed", proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout

    def list(self) -> list[PullRequest]:
        raw = self._gh("pr", "list", "--state", "all", "--limit", "20", "--json",
                       "number,title,headRefName,baseRefName,state,createdAt,body,url,headRefOid")
        prs = []
        for item in json.loads(raw or "[]"):
            branch = item["headRefName"]
            if not branch.startswith(BRANCH_PREFIXES):
                continue
            exists = self.git.branch_exists(branch)
            prs.append(PullRequest(
                id=branch, provider=self.name, title=item["title"], branch=branch,
                base=item["baseRefName"], state=item["state"].lower(), number=item["number"],
                url=item["url"], created_at=item["createdAt"], head_sha=item.get("headRefOid", "")[:7],
                body_md=item.get("body") or "",
                commits=[c.as_dict() for c in self.git.log(f"{item['baseRefName']}..{branch}")] if exists else [],
                files=self.git.diff_stat(item["baseRefName"], branch) if exists else [],
            ))
        return prs

    def get(self, pr_id: str) -> PullRequest:
        for pr in self.list():
            if pr.id == pr_id:
                return pr
        raise ApiError(404, "not_found", f"no pull request {pr_id!r}")

    def diff(self, pr_id: str) -> dict:
        pr = self.get(pr_id)
        return {"diff": self._gh("pr", "diff", str(pr.number)), "stat": pr.files}

    def merge(self, pr_id: str) -> str:
        pr = self.get(pr_id)
        self._gh("pr", "merge", str(pr.number), "--merge")
        self.git.run("fetch", "--quiet", "origin", pr.base, check=False)
        return self.git.head(f"origin/{pr.base}")


def _gh_ready(git: Git) -> bool:
    if not (git.is_repo() and git.has_remote() and shutil.which("gh")):
        return False
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def use_local_prs(settings: Settings, git: Git) -> bool:
    """Whether pull requests live in .tessera/prs/ rather than on GitHub.

    The demo needs a remote for the GitHub Actions beats but wants its pull
    requests local, because `gh pr list` has no notion of a demo reset: a
    merged pull request cannot be deleted from GitHub, so every run would
    leave one behind and the next run would open showing all of them. Local
    pull requests also keep replay working -- restoring a recording writes
    .tessera/prs/, which the GitHub provider never reads -- and keep the
    Merge button a local `git merge --no-ff` rather than a real `gh pr merge`.

    TESSERA_PR_PROVIDER=local pins that; anything else uses GitHub when the
    repository can support it.
    """
    return settings.pr_provider == "local" or not _gh_ready(git)


def provider_for(settings: Settings, git: Git):
    return (LocalPRProvider if use_local_prs(settings, git) else GitHubPRProvider)(settings, git)


class PRWatcher:
    """Notices new PRs, moved branch tips and merges, whoever caused them."""

    def __init__(self, provider, bus: EventBus, timeline: Timeline,
                 persona: Callable[[], str], run_for_branch: Callable[[str], str | None],
                 interval: float = 2.0) -> None:
        self.provider, self.bus, self.timeline = provider, bus, timeline
        self.persona, self.run_for_branch, self.interval = persona, run_for_branch, interval
        self.known: dict[str, tuple[str | None, str]] = {}
        self._primed = False

    def prime(self) -> None:
        self.known = {pr.id: (pr.head_sha, pr.state) for pr in self.provider.list()}
        self._primed = True

    def scan(self) -> list[PullRequest]:
        if not self._primed:
            self.prime()
            return []
        seen, new = set(), []
        for pr in self.provider.list():
            seen.add(pr.id)
            previous = self.known.get(pr.id)
            self.known[pr.id] = (pr.head_sha, pr.state)
            if previous is None:
                new.append(pr)
                self._emit("pr_opened", pr)
                self.timeline.append(
                    "pr_opened", "claude", f"PR opened: {pr.title}",
                    detail=f"{pr.branch} → {pr.base}, {len(pr.commits)} commit(s), {len(pr.files)} file(s)",
                    refs={"pr_id": pr.id, "branch": pr.branch, "incident_id": pr.incident_id,
                          "track": pr.track, "ticket": pr.ticket,
                          "run_id": self.run_for_branch(pr.branch)},
                )
                continue
            prev_sha, prev_state = previous
            if pr.state == "merged" and prev_state != "merged":
                self._emit("pr_merged", pr)
                if not any(e["type"] == "merged" and (e.get("refs") or {}).get("pr_id") == pr.id
                           for e in self.timeline.load()):
                    self.timeline.append("merged", "system", f"Merged {pr.branch} into {pr.base}",
                                         refs={"pr_id": pr.id, "branch": pr.branch, "incident_id": pr.incident_id,
                                           "track": pr.track, "ticket": pr.ticket})
            elif pr.head_sha != prev_sha and pr.state == "open":
                self._emit("pr_updated", pr)
                latest = pr.commits[0]["subject"] if pr.commits else "branch updated"
                self.timeline.append("pr_updated", self.persona(), f"PR updated: {latest}",
                                     detail=f"{pr.branch} now at {pr.head_sha}",
                                     refs={"pr_id": pr.id, "branch": pr.branch, "incident_id": pr.incident_id,
                                           "track": pr.track, "ticket": pr.ticket})
        for gone in set(self.known) - seen:
            del self.known[gone]
        return new

    def _emit(self, kind: str, pr: PullRequest) -> None:
        self.bus.publish("pr", {"type": kind, "pr": pr.as_dict()})

    async def run(self) -> None:
        import asyncio
        while True:
            try:
                await asyncio.to_thread(self.scan)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self.interval)


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None
