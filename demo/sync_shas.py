#!/usr/bin/env python3
"""
Rewrite the commit SHAs quoted in the presenter docs to match the current
history.

Rebuilding history changes every SHA, and quoting a stale one on stage is the
kind of small wrongness an audience notices. Commits are matched by message
rather than by position, so this stays correct if the history is reordered.

Recordings under demo/recordings/ are rewritten too. A recorded run narrates
the SHAs that were current when it was captured, so each recording carries a
`sha-state.json` with exactly those, and is rewritten from its own provenance.

Exits non-zero if a commit cannot be found, rather than reporting success and
changing nothing.
"""

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

# Stable identifier -> the commit-message fragment that finds it.
COMMITS = {
    "cause": "reduce risk-gateway pod memory",
    "pool": "raise risk-gateway connection pool",
    "docstring": "note fail-closed semantics",
}

DOCS = ["demo/DEMO_RUNBOOK.md", "demo/expected-output/act2-triage.md"]

RECORDINGS = REPO / "demo" / "recordings"
RECORDING_FILES = ("run.jsonl", "pr.md", "branch.patch", "meta.json")

# The SHAs the docs currently quote, recorded on the last successful sync.
# Kept in a state file rather than hardcoded, so an arbitrary number of history
# rebuilds stays self-healing -- a hardcoded list rots the moment someone
# rebuilds twice without editing this file.
STATE = REPO / "demo" / ".sha-state.json"

# Used only for the very first sync, before a state file exists.
SEED = {
    "cause": ["866f76b", "976f9d0", "7f90d70", "d9e0294", "7055921", "576ff6b"],
    "pool": ["18f6d0a", "8f69e85"],
    "docstring": ["db66e3e", "30cd56a", "e5221a1"],
}


def previous() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def resolve(fragment: str, fmt: str = "%h") -> str:
    sha = subprocess.run(
        ["git", "log", f"--format={fmt}", "-1", f"--grep={fragment}"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not sha:
        raise SystemExit(f"error: no commit matching {fragment!r}")
    return sha


def sync_recordings(current: dict) -> list[str]:
    """Rewrite each recording from the SHAs it recorded at capture time."""
    changed: list[str] = []
    if not RECORDINGS.exists():
        return changed
    for folder in sorted(p for p in RECORDINGS.iterdir() if p.is_dir()):
        state_path = folder / "sha-state.json"
        if not state_path.exists():
            continue  # no provenance recorded; leave it alone rather than guess
        try:
            recorded = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            continue
        rewrites = {old: current[name] for name, old in recorded.items()
                    if name in current and old != current[name]}
        full = {name: resolve(frag, "%H") for name, frag in COMMITS.items()}
        by_short = {current[name]: full[name] for name in COMMITS}
        files = list(RECORDING_FILES) + [p.name for p in folder.glob("*.ipynb")]
        for name in files:
            path = folder / name
            if not path.exists():
                continue
            text = original = path.read_text(encoding="utf-8", errors="surrogateescape")
            for old, new in rewrites.items():
                # Full SHAs first (git log --format=%H output), then short ones.
                # Hex boundaries, not word boundaries: inside a JSON string a SHA
                # can follow an escaped newline ("\\n" + SHA), which \b misses.
                text = re.sub(rf"(?<![0-9a-fA-F]){old}[0-9a-fA-F]{{33}}(?![0-9a-fA-F])", by_short[new], text)
                text = re.sub(rf"(?<![0-9a-fA-F]){old}(?![0-9a-fA-F])", new, text)
            if text != original:
                path.write_text(text, encoding="utf-8", errors="surrogateescape")
                changed.append(str(path.relative_to(REPO)))
        state_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    return changed


def main() -> None:
    current = {name: resolve(frag) for name, frag in COMMITS.items()}
    prior = previous()

    # Anything the docs quoted before -> what that same commit is called now.
    rewrites: dict[str, str] = {}
    for name, sha in current.items():
        olds = set(SEED.get(name, []))
        if name in prior:
            olds.add(prior[name])
        for old in olds:
            if old != sha:
                rewrites[old] = sha

    changed = []
    for rel in DOCS:
        p = REPO / rel
        text = original = p.read_text()
        for old, new in rewrites.items():
            text = re.sub(rf"\b{old}\b", new, text)
        if text != original:
            p.write_text(text)
            changed.append(rel)

        stale = {m for m in re.findall(r"\b[0-9a-f]{7}\b", text)
                 if m not in current.values()}
        if stale:
            raise SystemExit(
                f"error: {rel} references SHAs this script cannot account for: {sorted(stale)}.\n"
                f"       Current: {current}\n"
                f"       If a doc was hand-edited with a stale SHA, correct it there."
            )

    changed += sync_recordings(current)

    STATE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    print(f"SHAs current: {', '.join(f'{k}={v}' for k, v in current.items())}")
    print(f"  rewrote: {', '.join(changed) if changed else 'nothing (already current)'}")


if __name__ == "__main__":
    main()
