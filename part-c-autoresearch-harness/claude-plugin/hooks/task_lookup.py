"""Shared helpers for the autoresearch hooks.

Deliberately stdlib-only and Python 3.8-compatible: hooks run with whatever
`python3` is first on PATH (on macOS that is often the system 3.9), and the arh
package may not be installed in it. Everything the hooks need was written to
<task>/.arh/state.json by `arh init`.
"""

import fnmatch
import json
import os
import sys

TOOL_PATH_FIELDS = ("file_path", "notebook_path", "path")


def read_event():
    """Parse the hook payload on stdin. Returns None if it is unreadable."""
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return None


def tool_path(event):
    tool_input = event.get("tool_input") or {}
    for field in TOOL_PATH_FIELDS:
        value = tool_input.get(field)
        if value:
            return value
    return None


def find_task(file_path):
    """Walk up from `file_path` to the nearest initialised arh task.

    Returns (task_dir, state) or (None, None). Raises RuntimeError if a task is
    found but its state cannot be read -- the caller must then fail closed.
    """
    current = os.path.dirname(os.path.abspath(file_path))
    while True:
        spec = os.path.join(current, "autoresearch.toml")
        state_path = os.path.join(current, ".arh", "state.json")
        if os.path.isfile(spec) and os.path.isfile(state_path):
            try:
                with open(state_path) as handle:
                    return current, json.load(handle)
            except (ValueError, OSError) as exc:
                raise RuntimeError("cannot read " + state_path + ": " + str(exc))
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


def matches(rel_path, patterns):
    """Same matching rules as arh.spec.matches (tests keep the two in sync)."""
    rel = rel_path.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns or []:
        if pattern.endswith("/"):
            if ("/" + rel).find("/" + pattern) != -1:
                return True
        elif "/" not in pattern and any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatchcase(name, pattern):
                return True
        elif fnmatch.fnmatchcase(rel, pattern):
            return True
    return False


def relative_to(task_dir, file_path):
    return os.path.relpath(os.path.abspath(file_path), task_dir).replace(os.sep, "/")


def deny(reason):
    """Block the tool call. JSON on stdout with exit 0 is the documented way to
    return a decision; exit 2 also blocks but shows up as a hook error."""
    emit("PreToolUse", {"permissionDecision": "deny", "permissionDecisionReason": reason})
    sys.exit(0)


def add_context(event_name, text):
    emit(event_name, {"additionalContext": text})
    sys.exit(0)


def emit(event_name, payload):
    payload = dict(payload)
    payload["hookEventName"] = event_name
    print(json.dumps({"hookSpecificOutput": payload}))


def allow():
    """Stay silent: the harness has no opinion, so normal permissions apply."""
    sys.exit(0)
