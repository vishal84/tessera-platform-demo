"""
Recorded runs: the on-stage fallback.

A recording is a directory holding `run.jsonl` (every stdout line the headless
run produced, with a millisecond offset), `meta.json`, and -- when the run
produced one -- `pr.md` and `branch.patch`. Playing it back pushes the same
lines through the same parser as a live run, so the UI cannot tell the
difference except for the banner, and finishes by restoring the branch and PR
so the beats that follow still have something to work with.

The branch is kept as a format-patch, not a bundle: a bundle names its base
commit by SHA, and rebuilding the demo history changes every SHA. A patch
applies to any `main` whose files still match, which is what a rebuild gives.

`meta.json` may also carry `restore_files`, a list of `{from, to}` pairs copied
into the working tree after the patch applies. `git am` here runs without
`--3way`, so a patch hunk against a file that has drifted fails the whole
restore -- and a recording whose branch fails to apply leaves the following
beats with nothing. Anything that *modifies* a seeded file, rather than adding
one, is therefore better carried out of band: an executed notebook restores as
an uncommitted working-tree change, which is what a data scientist's tree looks
like mid-session anyway.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from .gitops import Git, GitError
from .prs import pr_filename
from .settings import Settings

GOLDEN = "golden"


def catalog(settings: Settings) -> list[dict]:
    entries = []
    for source, root in (("golden", settings.recordings_dir), ("run", settings.runs_dir)):
        if not root.exists():
            continue
        for folder in sorted(root.iterdir()):
            if not (folder / "run.jsonl").is_file():
                continue
            meta = _meta(folder)
            lines = _lines(folder)
            entries.append({
                "name": folder.name, "source": source, "path": str(folder),
                "incident_id": meta.get("incident_id"), "recorded_at": meta.get("started_at"),
                "track": _track_of(meta), "subject_id": _subject_of(meta),
                "duration_s": round((lines[-1]["t"] if lines else 0) / 1000, 1),
                "num_events": len(lines), "num_turns": meta.get("num_turns"), "cost_usd": meta.get("cost_usd"),
                "has_branch": (folder / "branch.patch").is_file(), "has_pr": (folder / "pr.md").is_file(),
                "branch": meta.get("branch"),
            })
    return entries


def resolve(settings: Settings, name: str, subject_id: str, track=None) -> Path | None:
    """`golden` means the committed recording for this subject; otherwise a run or recording name."""
    kind = getattr(track, "kind", "incident")
    if name == GOLDEN:
        for entry in catalog(settings):
            if entry["source"] == "golden" and entry["subject_id"] == subject_id and entry["track"] == kind:
                return Path(entry["path"])
        # Recordings committed before tracks existed have no meta to match on,
        # so the folder name is still a fallback: `triage-INC-4412`.
        prefix = getattr(track, "recording_prefix", "triage")
        for candidate in (settings.recordings_dir / f"{prefix}-{subject_id}",
                          settings.recordings_dir / f"triage-{subject_id}"):
            if (candidate / "run.jsonl").is_file():
                return candidate
        return None
    for root in (settings.runs_dir, settings.recordings_dir):
        candidate = root / name
        if (candidate / "run.jsonl").is_file():
            return candidate
    return None


def _track_of(meta: dict) -> str:
    return meta.get("track") or "incident"


def _subject_of(meta: dict) -> str | None:
    return meta.get("subject_id") or meta.get("incident_id")


async def play(folder: Path, ingest: Callable[[str], None], speed: Callable[[], float],
               stopped: Callable[[], bool], max_gap_ms: int = 8000) -> int:
    """Feed the recording to `ingest` with realistic pacing. Returns lines played."""
    previous = 0
    played = 0
    for entry in _lines(folder):
        if stopped():
            break
        gap = min(max(entry["t"] - previous, 0), max_gap_ms)
        previous = entry["t"]
        await asyncio.sleep(gap / 1000 / max(speed(), 0.1))
        ingest(entry["line"])
        played += 1
    return played


def restore_artifacts(folder: Path, settings: Settings, git: Git) -> dict:
    """Bring back the branch, the PR file and any out-of-band files.

    Order matters: the patch first, because `apply_patch` checks the branch out
    and will not do that over a dirty tree, then the file copies on top.
    """
    meta = _meta(folder)
    branch = meta.get("branch")
    restored: dict = {"branch": None, "pr": None, "files": [], "discarded": [],
                      "error": None, "note": None}
    patch = folder / "branch.patch"
    if branch and patch.is_file():
        base = meta.get("base") or "main"
        if git.branch_exists(branch):
            # Replayed twice without a reset. Say so rather than reporting nothing.
            restored["note"] = f"branch {branch} already exists; left as it is"
        else:
            # A recording is authoritative: reaching for one means abandoning
            # whatever the live attempt left behind, so tracked modifications
            # are discarded rather than treated as a reason to refuse. This
            # matters most on the data-scientist beat, where notebook 03 is
            # executed in place before anyone needs the fallback -- refusing on
            # a dirty tree meant the fallback could not run at the one moment
            # it exists for. Untracked files are left alone.
            dirty = [path for code, path in git.status() if code != "??"]
            if dirty:
                git.reset_hard(base)
                restored["discarded"] = dirty
            try:
                git.apply_patch(patch, branch, base)
                restored["branch"] = branch
            except GitError as exc:
                restored["error"] = f"could not apply branch.patch: {exc}"[:300]
    pr_src = folder / "pr.md"
    if pr_src.is_file() and branch:
        settings.prs_dir.mkdir(parents=True, exist_ok=True)
        target = settings.prs_dir / pr_filename(branch)
        if not target.exists():
            shutil.copy2(pr_src, target)
            restored["pr"] = branch
    restored["files"] = _restore_files(folder, settings, meta)
    return restored


def _restore_files(folder: Path, settings: Settings, meta: dict) -> list[str]:
    """Copy `restore_files` entries into the working tree.

    A recording is committed data, but it is still data driving a file write,
    so both ends are confined: sources to the recording, targets to the repo.
    """
    written: list[str] = []
    for entry in meta.get("restore_files") or []:
        if not isinstance(entry, dict):
            continue
        source, target = entry.get("from"), entry.get("to")
        if not source or not target:
            continue
        src = (folder / source).resolve()
        dst = (settings.repo_root / target).resolve()
        if not _inside(src, folder.resolve()) or not _inside(dst, settings.repo_root.resolve()):
            continue
        if not src.is_file() or (entry.get("when") == "missing" and dst.exists()):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.append(str(dst.relative_to(settings.repo_root)))
    return written


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _meta(folder: Path) -> dict:
    path = folder / "meta.json"
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except json.JSONDecodeError:
        return {}


def _lines(folder: Path) -> list[dict]:
    out = []
    for raw in (folder / "run.jsonl").read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and "line" in entry:
            entry.setdefault("t", 0)
            out.append(entry)
    return out
