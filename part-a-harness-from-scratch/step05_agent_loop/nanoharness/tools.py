"""The built-in tools. Each one is a plain function; @tool does the paperwork.

Docstrings here are prompt engineering: the model reads them verbatim.
"""
import os
import signal
import subprocess
from pathlib import Path

from .registry import tool

TIMEOUT_SECONDS = 30
MAX_ENTRIES = 300


@tool
def bash(command: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """Run a shell command in the current working directory and return its combined
    stdout and stderr plus the exit code.

    Args:
        command: The command to run, for example "ls -la" or "python -m pytest -q".
        timeout: Seconds to wait before the command is killed.
    """
    process = subprocess.Popen(
        ["bash", "-c", command],
        stdin=subprocess.DEVNULL,  # a command that waits for input would hang the agent forever
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # the model wants the error text as much as the output
        start_new_session=True,  # own process group, so a timeout can kill the children too
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        output = _kill_group(process)
        return f"{output}\n[timed out after {timeout}s, process group killed]"
    except KeyboardInterrupt:
        _kill_group(process)
        raise
    return f"{output}\n[exit code {process.returncode}]"


@tool
def read_file(path: str, offset: int = 1, limit: int = 400) -> str:
    """Read a text file and return it with line numbers.

    Args:
        path: File to read, relative to the working directory or absolute.
        offset: 1-based line number to start at.
        limit: Maximum number of lines to return.
    """
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    if offset < 1:
        offset = 1
    window = lines[offset - 1 : offset - 1 + limit]
    if not window:
        return f"(no lines at offset {offset}; the file has {len(lines)} lines)"
    numbered = "\n".join(f"{number:>5}  {text}" for number, text in enumerate(window, start=offset))
    remaining = len(lines) - (offset - 1 + len(window))
    if remaining > 0:
        numbered += f"\n[{remaining} more lines; call read_file again with offset={offset + len(window)}]"
    return numbered


@tool
def list_dir(path: str = ".") -> str:
    """List a directory. Sub-directories end with a slash; files show their size.

    Args:
        path: Directory to list, relative to the working directory or absolute.
    """
    entries = sorted(Path(path).iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    if not entries:
        return "(empty directory)"
    lines = []
    for item in entries[:MAX_ENTRIES]:
        lines.append(f"{item.name}/" if item.is_dir() else f"{item.name}  ({item.stat().st_size} bytes)")
    if len(entries) > MAX_ENTRIES:
        lines.append(f"[{len(entries) - MAX_ENTRIES} more entries not shown]")
    return "\n".join(lines)


def _kill_group(process: subprocess.Popen) -> str:
    """Kill the whole process group; `sleep 100 & wait` must not survive us."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    output, _ = process.communicate()
    return output or ""
