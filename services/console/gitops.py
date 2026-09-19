"""
Thin, synchronous git helpers. Every call shells out; git is fast enough that
callers on the event loop wrap only the polling paths in `asyncio.to_thread`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

FALLBACK_IDENTITY = {"GIT_AUTHOR_NAME": "Tessera Console", "GIT_AUTHOR_EMAIL": "console@tessera.test",
                     "GIT_COMMITTER_NAME": "Tessera Console", "GIT_COMMITTER_EMAIL": "console@tessera.test"}


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    short: str
    author: str
    date: str
    subject: str

    def as_dict(self) -> dict:
        return {"sha": self.sha, "short": self.short, "author": self.author,
                "date": self.date, "subject": self.subject}


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)
        self._env: dict[str, str] | None = None

    def env(self) -> dict[str, str]:
        """The caller's git identity when one is configured, a console identity otherwise (CI, fresh machines)."""
        if self._env is None:
            has_identity = subprocess.run(["git", "config", "user.email"], cwd=self.repo,
                                          capture_output=True).returncode == 0
            self._env = dict(os.environ) if has_identity else {**os.environ, **FALLBACK_IDENTITY}
        return self._env

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, env=self.env())
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    # --- read -------------------------------------------------------------
    def is_repo(self) -> bool:
        return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=self.repo,
                              capture_output=True).returncode == 0

    def head(self, ref: str = "HEAD") -> str:
        return self.run("rev-parse", ref).strip()

    def short(self, ref: str = "HEAD") -> str:
        return self.run("rev-parse", "--short", ref).strip()

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def status(self) -> list[tuple[str, str]]:
        lines = self.run("status", "--porcelain").splitlines()
        return [(line[:2], line[3:]) for line in lines if line]

    def is_clean(self, include_untracked: bool = True) -> bool:
        entries = self.status()
        if not include_untracked:
            entries = [entry for entry in entries if entry[0] != "??"]
        return not entries

    def branches(self, glob: str = "*") -> list[str]:
        out = self.run("for-each-ref", "--format=%(refname:short)", f"refs/heads/{glob}")
        return [line for line in out.splitlines() if line]

    def branch_exists(self, name: str) -> bool:
        return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
                              cwd=self.repo, capture_output=True).returncode == 0

    def show(self, ref: str, path: str) -> str | None:
        proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=self.repo,
                              capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 else None

    def log(self, rev_range: str = "HEAD", limit: int = 50) -> list[Commit]:
        fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s"
        out = self.run("log", f"--format={fmt}", f"-{limit}", rev_range, check=False)
        commits = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 5:
                commits.append(Commit(*parts))
        return commits

    def diff(self, base: str, branch: str) -> str:
        return self.run("diff", f"{base}...{branch}", check=False)

    def diff_stat(self, base: str, branch: str) -> list[dict]:
        out = self.run("diff", "--numstat", f"{base}...{branch}", check=False)
        files = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                added, deleted, path = parts
                files.append({"path": path,
                              "additions": int(added) if added.isdigit() else 0,
                              "deletions": int(deleted) if deleted.isdigit() else 0})
        return files

    def has_remote(self) -> bool:
        return bool(self.run("remote", check=False).strip())

    def tag_exists(self, name: str) -> bool:
        return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{name}"],
                              cwd=self.repo, capture_output=True).returncode == 0

    def merge_base_is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                              cwd=self.repo, capture_output=True).returncode == 0

    # --- write ------------------------------------------------------------
    def checkout(self, ref: str) -> None:
        self.run("checkout", "--quiet", ref)

    def reset_hard(self, ref: str) -> None:
        """Discard tracked modifications and put the tree at `ref`. Untracked files stay."""
        self.run("reset", "--quiet", "--hard", ref)

    def merge_no_ff(self, branch: str, message: str) -> str:
        self.run("merge", "--no-ff", "--no-edit", "-m", message, branch)
        return self.head()

    def format_patch(self, base: str, branch: str) -> str:
        """Every commit on `branch` beyond `base`, as one mbox-style patch (messages and authors kept)."""
        return self.run("format-patch", "--stdout", f"{base}..{branch}")

    def apply_patch(self, path: Path, branch: str, base: str = "main") -> None:
        """Recreate `branch` from `base` by applying a format-patch file. Leaves the tree on the branch."""
        self.run("checkout", "--quiet", "-b", branch, base)
        try:
            self.run("am", "--quiet", str(path))
        except GitError:
            self.run("am", "--abort", check=False)
            self.run("checkout", "--quiet", base)
            self.run("branch", "-D", branch, check=False)
            raise
