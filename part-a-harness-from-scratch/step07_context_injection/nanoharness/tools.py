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


@tool
def write_file(path: str, content: str) -> str:
    """Create a file, or overwrite it completely. Missing parent directories are created.
    Prefer edit_file for changing part of an existing file.

    Args:
        path: File to write, relative to the working directory or absolute.
        content: The complete new content of the file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    verb = "Overwrote" if existed else "Created"
    return f"{verb} {path} ({len(content.splitlines())} lines)"


@tool
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """Replace an exact piece of text in a file. Read the file first and copy the text
    exactly, including indentation, but without the line numbers read_file adds.

    Args:
        path: File to edit.
        old_text: The exact text to find. It must appear exactly once unless replace_all is true.
        new_text: The text to put in its place.
        replace_all: Replace every occurrence instead of requiring a unique match.
    """
    if not old_text:
        return "Error: old_text is empty. Use write_file to create a file."
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    found = text.count(old_text)
    if found == 0:
        return (
            f"Error: old_text was not found in {path}. Read the file again and copy the exact "
            "text, including whitespace."
        )
    if found > 1 and not replace_all:
        return (
            f"Error: old_text appears {found} times in {path}. Include more surrounding lines to "
            "make it unique, or set replace_all to true."
        )
    target.write_text(text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1),
                      encoding="utf-8")
    return f"Edited {path}: replaced {found if replace_all else 1} occurrence(s)"


def _kill_group(process: subprocess.Popen) -> str:
    """Kill the whole process group; `sleep 100 & wait` must not survive us."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    output, _ = process.communicate()
    return output or ""
