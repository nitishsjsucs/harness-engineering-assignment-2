"""Step 03: our first tool.

A tool is two things that must agree with each other:
  1. a JSON schema, which is all the model ever sees;
  2. a Python function, which is what actually runs on this machine.

The model can only ask. Running it is our decision.
"""
import os
import signal
import subprocess

TIMEOUT_SECONDS = 30

BASH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a shell command in the current working directory and return its "
            "combined stdout and stderr plus the exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": 'The command to run, e.g. "ls -la" or "git status".',
                }
            },
            "required": ["command"],
        },
    },
}


def run_bash(command: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """Run one shell command and return what the model needs to see."""
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


def _kill_group(process: subprocess.Popen) -> str:
    """Kill the whole process group; `sleep 100 & wait` must not survive us."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    output, _ = process.communicate()
    return output or ""
