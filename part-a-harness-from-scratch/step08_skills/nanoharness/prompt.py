"""What surrounds the conversation: a stable prefix and a volatile tail.

Two kinds of context, and the difference is the whole point of this step.

* Stable: the base instructions plus the project's own instruction file. Built
  once per session and sent as message 0 every time, byte for byte identical, so
  the provider can serve it from its prefix cache.
* Volatile: cwd, git branch, the clock. These change between calls, so they are
  appended to the *request* as the last message and never stored in the
  transcript. If they were stored, every turn would rewrite history and every
  turn would miss the cache.
"""
import subprocess
from datetime import datetime
from pathlib import Path

INSTRUCTION_FILE = "AGENTS.md"
MAX_LISTED_FILES = 10

BASE = (
    "You are nanoharness, a coding agent working in the user's project directory.\n"
    "Use your tools to inspect the real files and run real commands instead of guessing.\n"
    "Before editing a file, read it. Make the smallest edit that does the job.\n"
    "Work in small steps: look, act, check. When the task is done, reply with a short summary "
    "of what you did and what you found."
)


def system_prompt(root: Path, extras: list[str] | tuple[str, ...] = ()) -> str:
    """The stable prefix: base instructions + the project's instruction file + extras.

    `extras` are other stable sections (step 08 passes the skill catalogue).
    """
    parts = [BASE]
    instructions = Path(root) / INSTRUCTION_FILE
    if instructions.is_file():
        body = instructions.read_text(encoding="utf-8", errors="replace").strip()
        parts.append(f"# Project instructions from {INSTRUCTION_FILE}\n{body}")
    parts.extend(section for section in extras if section)
    return "\n\n".join(parts)


def environment_block(root: Path) -> str:
    """The volatile tail: facts that would be stale if we had stored them."""
    lines = [
        "This block is attached by the harness before every request. It is not part of the "
        "conversation and the user did not type it.",
        f"cwd: {root}",
        f"now: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
    ]
    # --show-current also works in a repository that has no commit yet.
    branch = git(root, "branch", "--show-current")
    if branch:
        lines.append(f"git branch: {branch}")
        lines.append(git_status_summary(root))
    return "<environment>\n" + "\n".join(lines) + "\n</environment>"


def git_status_summary(root: Path) -> str:
    status = git(root, "status", "--porcelain")
    if status is None:
        return "git status: unavailable"
    entries = [line for line in status.splitlines() if line.strip()]
    if not entries:
        return "git status: clean"
    names = [line[3:] for line in entries[:MAX_LISTED_FILES]]
    more = f" (+{len(entries) - MAX_LISTED_FILES} more)" if len(entries) > MAX_LISTED_FILES else ""
    return f"git status: {len(entries)} changed: {', '.join(names)}{more}"


def git(root: Path, *args: str) -> str | None:
    """Run a read-only git command; None when this is not a repository or git is missing."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
