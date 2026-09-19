"""Git as the harness's undo button.

Two modes, chosen at `arh init`:

  isolated (default)  a private repository at <task>/.arh/git whose work tree
                      is the task directory. It never touches any enclosing
                      repository, so a task can live inside your project (or
                      inside a course repo) without creating branches there.

  repo                use the git repository that already contains the task
                      (Karpathy's setup). The harness creates the branch
                      autoresearch/<tag> there and only ever stages paths
                      inside the task directory.

Either way, every path this module returns is relative to the task directory.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

FALLBACK_IDENTITY = {
    "GIT_AUTHOR_NAME": "arh",
    "GIT_AUTHOR_EMAIL": "arh@localhost",
    "GIT_COMMITTER_NAME": "arh",
    "GIT_COMMITTER_EMAIL": "arh@localhost",
}


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, task_dir: Path, mode: str):
        if mode not in ("isolated", "repo"):
            raise ValueError(f"unknown git mode {mode!r}")
        self.task_dir = Path(task_dir)
        self.mode = mode
        self.git_dir = self.task_dir / ".arh" / "git"
        self._env_cache: dict | None = None

    # -- plumbing ----------------------------------------------------------
    def _cmd(self) -> list[str]:
        if self.mode == "isolated":
            return ["git", f"--git-dir={self.git_dir}", f"--work-tree={self.task_dir}"]
        return ["git"]

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            self._cmd() + list(args), cwd=self.task_dir, env=self._env(), capture_output=True, text=True
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    def _env(self) -> dict:
        if self._env_cache is not None:
            return self._env_cache
        # Strip inherited GIT_* variables (e.g. when arh runs inside a git hook)
        # so they cannot redirect us to some other repository.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        # Commits must never fail for lack of user.email on a fresh machine.
        probe = subprocess.run(["git", "config", "user.email"], cwd=self.task_dir, env=env, capture_output=True, text=True)
        if not probe.stdout.strip():
            env.update(FALLBACK_IDENTITY)
        self._env_cache = env
        return env

    # -- setup -------------------------------------------------------------
    def enclosing_repo(self) -> Path | None:
        """Top level of a repository that contains the task dir, if any."""
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=self.task_dir, capture_output=True, text=True
        )
        return Path(proc.stdout.strip()) if proc.returncode == 0 else None

    def init_isolated(self, branch: str, ignore_patterns) -> None:
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        self.run("init", "--quiet", f"--initial-branch={branch}")
        exclude = self.git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(ignore_patterns) + "\n")

    def create_branch(self, branch: str) -> None:
        if self.run("branch", "--list", branch).strip():
            raise GitError(f"branch {branch} already exists; pick another --tag")
        self.run("checkout", "--quiet", "-b", branch)

    # -- queries -----------------------------------------------------------
    def head(self) -> str:
        return self.run("rev-parse", "HEAD").strip()

    def has_commits(self) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", "HEAD", check=False).strip() != ""

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def changed_files(self) -> tuple[list[str], list[str]]:
        """(tracked files that differ from HEAD, untracked files), both limited
        to the task directory and relative to it."""
        tracked = self.run("diff", "--name-only", "--relative", "HEAD", "--", ".").split("\n")
        untracked = self.run("ls-files", "--others", "--exclude-standard", "--", ".").split("\n")
        return [p for p in tracked if p], [p for p in untracked if p]

    def is_tracked(self, rel: str) -> bool:
        return self.run("ls-files", "--error-unmatch", "--", rel, check=False).strip() != ""

    def diff(self, paths: list[str]) -> str:
        if not paths:
            return ""
        return self.run("diff", "--relative", "HEAD", "--", *paths)

    def show(self, commit: str, rel: str) -> bytes:
        prefix = self.run("rev-parse", "--show-prefix").strip()  # "" in isolated mode
        proc = subprocess.run(
            self._cmd() + ["show", f"{commit}:{prefix}{rel}"], cwd=self.task_dir, env=self._env(), capture_output=True
        )
        if proc.returncode != 0:
            raise GitError(f"cannot read {rel} at {commit}")
        return proc.stdout

    # -- mutations -----------------------------------------------------------
    def commit_paths(self, paths: list[str], message: str) -> str:
        """Stage and commit exactly `paths` (additions, edits, deletions) and
        nothing else, even if the enclosing repo has other staged work."""
        self.run("add", "--all", "--", *paths)
        self.run("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *paths)
        return self.head()

    def restore(self, tracked: list[str], commit: str = "HEAD") -> None:
        """Put tracked paths back exactly as they are in `commit`."""
        if not tracked:
            return
        present, deleted_in_commit = [], []
        for rel in tracked:
            (present if self._exists_in(commit, rel) else deleted_in_commit).append(rel)
        if present:
            self.run("checkout", commit, "--", *present)
        for rel in deleted_in_commit:
            # Added to the index but never committed: drop it from both.
            self.run("rm", "--quiet", "--cached", "--ignore-unmatch", "--", rel)
            (self.task_dir / rel).unlink(missing_ok=True)

    def _exists_in(self, commit: str, rel: str) -> bool:
        try:
            self.show(commit, rel)
            return True
        except GitError:
            return False

    def log(self, n: int = 20) -> str:
        return self.run("log", f"-{n}", "--oneline", "--decorate")
