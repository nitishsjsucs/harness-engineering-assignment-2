"""A kernel-enforced box around every shell command.

The permission engine of step 11 reads the command and decides whether to ask.
This module assumes the reading was wrong. Even a command the user approved runs
with: read anywhere, write only inside the project (plus the temp directory),
and no network at all.

    macOS  -> sandbox-exec (Seatbelt) with an inline profile
    Linux  -> bubblewrap, if bwrap is installed
    other  -> "none", and we say so in the banner instead of pretending
"""
import os
import platform
import shutil
import tempfile
from pathlib import Path

SEATBELT, BUBBLEWRAP, NONE = "seatbelt", "bubblewrap", "none"

# Seatbelt profile. Paths arrive as -D parameters so that spaces and quotes in
# the project path cannot break out of the profile syntax.
SEATBELT_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write*
    (subpath (param "PROJECT"))
    (subpath (param "TMPDIR"))
    (literal "/dev/null")
    (regex #"^/dev/(tty|fd/|stdout|stderr)"))
"""


def detect() -> str:
    """Pick the strongest sandbox this machine actually has."""
    system = platform.system()
    if system == "Darwin" and Path("/usr/bin/sandbox-exec").exists():
        return SEATBELT
    if system == "Linux" and shutil.which("bwrap"):
        return BUBBLEWRAP
    return NONE


def wrap(command: str, root: Path | str, kind: str) -> list[str]:
    """The argv that runs `command` under the chosen sandbox."""
    project = os.path.realpath(str(root))  # /tmp is a symlink on macOS; the profile needs the real path
    temporary = os.path.realpath(tempfile.gettempdir())
    if kind == SEATBELT:
        return [
            "sandbox-exec",
            "-p", SEATBELT_PROFILE,
            "-D", f"PROJECT={project}",
            "-D", f"TMPDIR={temporary}",
            "bash", "-c", command,
        ]
    if kind == BUBBLEWRAP:
        return [
            "bwrap",
            "--ro-bind", "/", "/",  # everything readable...
            "--bind", project, project,  # ...but only the project writable
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--unshare-net",  # no network namespace: no network
            "--die-with-parent",
            "--chdir", project,
            "bash", "-c", command,
        ]
    return ["bash", "-c", command]


def describe(kind: str) -> str:
    return {
        SEATBELT: "seatbelt (write only inside the project, no network)",
        BUBBLEWRAP: "bubblewrap (write only inside the project, no network)",
        NONE: "none (commands run with your full user rights)",
    }[kind]
