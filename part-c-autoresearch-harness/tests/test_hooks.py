"""The Claude Code hooks, exercised the way Claude Code runs them: a JSON
payload on stdin, a JSON decision on stdout.

They are plain scripts on purpose -- no arh import -- so they keep working with
whatever `python3` the assistant's machine has.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from arh.spec import matches as engine_matches

HOOKS = Path(__file__).resolve().parents[1] / "claude-plugin" / "hooks"
sys.path.insert(0, str(HOOKS))
import task_lookup  # noqa: E402  (the hooks' own copy of the matching rules)


def run_hook(script: str, payload, task_dir=None):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / script)], input=text, capture_output=True, text=True, cwd=task_dir or "."
    )
    decision = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}
    return proc, decision


def edit_event(path, tool="Edit"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"file_path": str(path)}}


# ------------------------------------------------------------- PreToolUse
def test_a_frozen_file_is_blocked(harness):
    proc, decision = run_hook("guard_frozen.py", edit_event(harness.root / "prepare.py"))
    assert proc.returncode == 0
    assert decision["permissionDecision"] == "deny"
    assert "frozen evaluation file" in decision["permissionDecisionReason"]
    assert "train.py" in decision["permissionDecisionReason"], "the reason says what IS allowed"


def test_an_editable_file_is_allowed(harness):
    proc, decision = run_hook("guard_frozen.py", edit_event(harness.root / "train.py"))
    assert proc.returncode == 0 and decision == {}, "no decision means normal permissions apply"


def test_the_ledger_is_protected(harness):
    _, decision = run_hook("guard_frozen.py", edit_event(harness.state_dir / "results.tsv", tool="Write"))
    assert decision["permissionDecision"] == "deny" and "ledger" in decision["permissionDecisionReason"]


def test_the_spec_itself_is_protected(harness):
    _, decision = run_hook("guard_frozen.py", edit_event(harness.root / "autoresearch.toml"))
    assert decision["permissionDecision"] == "deny" and "not on the editable list" in decision["permissionDecisionReason"]


def test_files_outside_a_task_are_none_of_our_business(tmp_path):
    (tmp_path / "somewhere.py").write_text("x = 1\n")
    _, decision = run_hook("guard_frozen.py", edit_event(tmp_path / "somewhere.py"))
    assert decision == {}


def test_a_task_that_was_never_initialised_is_not_enforced(task_dir):
    _, decision = run_hook("guard_frozen.py", edit_event(task_dir / "prepare.py"))
    assert decision == {}, "before `arh init` there is no experiment to protect"


def test_other_tools_pass_through(harness):
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    _, decision = run_hook("guard_frozen.py", payload)
    assert decision == {}


@pytest.mark.parametrize("payload", ["not json at all", {"tool_name": "Edit", "tool_input": {}}])
def test_the_hook_fails_closed(payload):
    _, decision = run_hook("guard_frozen.py", payload)
    assert decision["permissionDecision"] == "deny" and "fail closed" in decision["permissionDecisionReason"]


def test_unreadable_task_state_fails_closed(harness):
    (harness.state_dir / "state.json").write_text("{ this is not json")
    _, decision = run_hook("guard_frozen.py", edit_event(harness.root / "train.py"))
    assert decision["permissionDecision"] == "deny" and "fail closed" in decision["permissionDecisionReason"]


# ------------------------------------------------------------ PostToolUse
def test_the_reminder_fires_on_an_editable_file(harness):
    _, decision = run_hook("remind_run.py", edit_event(harness.root / "train.py"))
    assert "arh run" in decision["additionalContext"]
    assert decision["hookEventName"] == "PostToolUse"


def test_the_reminder_stays_quiet_elsewhere(harness, tmp_path):
    (tmp_path / "other.py").write_text("x = 1\n")
    _, decision = run_hook("remind_run.py", edit_event(tmp_path / "other.py"))
    assert decision == {}


# ------------------------------------------------ the two copies of the rules
@pytest.mark.parametrize(
    "path,patterns",
    [
        ("train.py", ["train.py"]),
        ("sub/train.py", ["train.py"]),
        ("sub/train.py", ["sub/*.py"]),
        ("data/val.npy", ["data/"]),
        ("x.pyc", ["*.pyc"]),
        ("deep/x.pyc", ["*.pyc"]),
        (".arh/state.json", [".arh/"]),
        ("model/net.py", ["model/*.py", "train.py"]),
    ],
)
def test_hook_and_engine_agree_on_path_matching(path, patterns):
    assert task_lookup.matches(path, patterns) == engine_matches(path, patterns)
