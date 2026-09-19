"""Offline test for step 12: the sandbox argv, the real kernel box, and output capping."""
import io
import json
import os
from pathlib import Path

import pytest
from rich.console import Console

from nanoharness import registry, sandbox, tools
from nanoharness.agent import Agent
from nanoharness.ui import UI


def quiet_ui():
    return UI(console=Console(file=io.StringIO(), width=100, force_terminal=False))


def test_detect_returns_a_known_kind():
    assert sandbox.detect() in (sandbox.SEATBELT, sandbox.BUBBLEWRAP, sandbox.NONE)
    assert "project" in sandbox.describe(sandbox.detect()) or "full user rights" in sandbox.describe(sandbox.detect())


def test_wrap_builds_the_expected_argv(tmp_path):
    plain = sandbox.wrap("echo hi", tmp_path, sandbox.NONE)
    assert plain == ["bash", "-c", "echo hi"]

    seatbelt = sandbox.wrap("echo hi", tmp_path, sandbox.SEATBELT)
    assert seatbelt[0] == "sandbox-exec"
    assert seatbelt[-3:] == ["bash", "-c", "echo hi"]
    assert f"PROJECT={os.path.realpath(tmp_path)}" in seatbelt
    assert "(deny network*)" in seatbelt[2] and "(deny file-write*)" in seatbelt[2]

    bwrap = sandbox.wrap("echo hi", tmp_path, sandbox.BUBBLEWRAP)
    assert bwrap[0] == "bwrap"
    assert "--unshare-net" in bwrap and "--ro-bind" in bwrap
    # read-only root first, writable project second: order matters to bubblewrap
    assert bwrap.index("--ro-bind") < bwrap.index("--bind")


def test_project_path_with_spaces_is_passed_as_a_parameter(tmp_path):
    spaced = tmp_path / "My Project (v2)"
    spaced.mkdir()
    argv = sandbox.wrap("ls", spaced, sandbox.SEATBELT)
    # The path travels as its own argv entry, never spliced into the profile text.
    assert f"PROJECT={os.path.realpath(spaced)}" in argv
    assert str(spaced) not in argv[2]


@pytest.mark.skipif(sandbox.detect() != sandbox.SEATBELT, reason="needs macOS sandbox-exec")
def test_seatbelt_really_blocks_writes_and_network(tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    assert agent.sandbox == sandbox.SEATBELT

    inside = registry.run_tool("bash", json.dumps({"command": "echo ok > inside.txt"}), agent=agent)
    assert "[exit code 0]" in inside
    assert (tmp_path / "inside.txt").read_text() == "ok\n"

    outside = registry.run_tool(
        "bash", json.dumps({"command": f"echo bad > {Path.home() / 'nanoharness_should_not_exist.txt'}"}), agent=agent
    )
    assert "Operation not permitted" in outside
    assert not (Path.home() / "nanoharness_should_not_exist.txt").exists()

    network = registry.run_tool(
        "bash",
        json.dumps({"command": "python3 -c 'import socket; socket.create_connection((\"1.1.1.1\", 53), timeout=3)'"}),
        agent=agent,
    )
    assert "[exit code 0]" not in network


def test_reading_outside_the_project_still_works(tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    result = registry.run_tool("bash", json.dumps({"command": "cat /etc/hosts | head -1"}), agent=agent)
    assert "[exit code 0]" in result  # read anywhere, write nowhere else


def test_without_an_agent_the_tool_still_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "[exit code 0]" in registry.run_tool("bash", json.dumps({"command": "echo plain"}))


def test_cap_output_keeps_head_and_tail_and_spills_the_rest():
    text = "\n".join(f"line {i}" for i in range(5000))
    capped = tools.cap_output(text, limit=2000)

    assert len(capped) < len(text)
    assert capped.startswith("line 0")
    assert capped.rstrip().endswith("line 4999")
    assert "characters cut out of" in capped

    spill = capped.split("The full output is in ")[1].split(" - ")[0]
    assert Path(spill).read_text() == text  # nothing is actually lost
    Path(spill).unlink()


def test_short_output_is_untouched():
    assert tools.cap_output("small") == "small"


def test_bash_output_is_capped(tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    monkey_limit = 500
    original = tools.MAX_OUTPUT_CHARS
    tools.MAX_OUTPUT_CHARS = monkey_limit
    try:
        result = registry.run_tool("bash", json.dumps({"command": "seq 1 5000"}), agent=agent)
    finally:
        tools.MAX_OUTPUT_CHARS = original
    assert "characters cut out of" in result
    spill = result.split("The full output is in ")[1].split(" - ")[0]
    assert "4999" in Path(spill).read_text()
    Path(spill).unlink()


def test_no_sandbox_is_honest_not_silent():
    assert "full user rights" in sandbox.describe(sandbox.NONE)
