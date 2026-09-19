"""Offline test for step 06: the edit tools, and a UI that knows nothing about models."""
import copy
import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from nanoharness import llm, registry, ui as ui_module
from nanoharness.agent import Agent
from nanoharness.ui import UI


def quiet_ui():
    """A UI that renders into a string buffer instead of the terminal."""
    return UI(console=Console(file=io.StringIO(), width=100, force_terminal=False))


def says(text):
    return {"role": "assistant", "content": text}


def calls(*specs, content=None):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for cid, name, args in specs
        ],
    }


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 20, "completion_tokens": 5, "cached_tokens": 0, "cost": 0.0}


def test_write_file_creates_parents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = registry.run_tool("write_file", json.dumps({"path": "pkg/mod.py", "content": "x = 1\n"}))
    assert result.startswith("Created")
    assert (tmp_path / "pkg" / "mod.py").read_text() == "x = 1\n"

    again = registry.run_tool("write_file", json.dumps({"path": "pkg/mod.py", "content": "x = 2\n"}))
    assert again.startswith("Overwrote")


def test_edit_file_requires_a_unique_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("code.py").write_text("a = 1\nb = 1\na = 1\n")

    twice = registry.run_tool("edit_file", json.dumps({"path": "code.py", "old_text": "a = 1", "new_text": "a = 9"}))
    assert twice.startswith("Error: old_text appears 2 times")
    assert Path("code.py").read_text() == "a = 1\nb = 1\na = 1\n"  # nothing was written

    missing = registry.run_tool("edit_file", json.dumps({"path": "code.py", "old_text": "zzz", "new_text": "q"}))
    assert missing.startswith("Error: old_text was not found")

    unique = registry.run_tool("edit_file", json.dumps({"path": "code.py", "old_text": "b = 1", "new_text": "b = 2"}))
    assert unique.startswith("Edited")
    assert Path("code.py").read_text() == "a = 1\nb = 2\na = 1\n"


def test_edit_file_replace_all(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("code.py").write_text("a = 1\na = 1\n")
    result = registry.run_tool(
        "edit_file", json.dumps({"path": "code.py", "old_text": "a = 1", "new_text": "a = 2", "replace_all": True})
    )
    assert "replaced 2 occurrence" in result
    assert Path("code.py").read_text() == "a = 2\na = 2\n"


def test_empty_old_text_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("code.py").write_text("x\n")
    assert registry.run_tool(
        "edit_file", json.dumps({"path": "code.py", "old_text": "", "new_text": "y"})
    ).startswith("Error: old_text is empty")


def test_agent_writes_then_edits_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = FakeLLM(
        calls(("c1", "write_file", {"path": "calc.py", "content": "def add(a, b):\n    return a - b\n"})),
        calls(("c2", "edit_file", {"path": "calc.py", "old_text": "a - b", "new_text": "a + b"})),
        says("Fixed the sign."),
    )
    monkeypatch.setattr(llm, "chat", fake)

    agent = Agent(ui=quiet_ui())
    assert agent.run("write calc.py with add(), then fix the bug") == "Fixed the sign."
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_ui_renders_calls_results_and_usage():
    buffer = io.StringIO()
    ui = UI(console=Console(file=buffer, width=100, force_terminal=False))
    ui.tool_call("bash", json.dumps({"command": "pytest -q"}))
    ui.tool_result("line1\nline2\nline3", lines=2)
    ui.usage({"prompt_tokens": 7, "completion_tokens": 2, "cached_tokens": 0, "cost": 0.000123})
    text = buffer.getvalue()
    assert "$ pytest -q" in text
    assert "(1 more lines)" in text  # long results are shortened on screen only
    assert "cost=$0.000123" in text


def test_describe_summarises_each_tool():
    assert ui_module.describe("bash", {"command": "ls"}) == "$ ls"
    assert ui_module.describe("write_file", {"path": "a.py", "content": "1\n2\n"}) == "a.py (2 lines)"
    assert ui_module.describe("read_file", {"path": "a.py", "offset": 40}) == "a.py from line 40"
    assert ui_module.describe("bash", "not json at all") == "not json at all"


def test_ui_module_does_not_know_about_models():
    """ui.py must stay swappable: no llm, no openai, no registry imports."""
    source = Path(ui_module.__file__).read_text()
    for forbidden in ("import openai", "from . import llm", "from .registry", "registry."):
        assert forbidden not in source


def test_model_never_sees_the_shortened_output(tmp_path, monkeypatch):
    """tool_result() truncates for the terminal; the transcript keeps everything."""
    monkeypatch.chdir(tmp_path)
    Path("big.txt").write_text("\n".join(f"line {i}" for i in range(50)))
    fake = FakeLLM(calls(("c1", "read_file", {"path": "big.txt"})), says("read it"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(ui=quiet_ui())
    agent.run("read big.txt")
    tool_result = [m for m in agent.messages if m["role"] == "tool"][0]["content"]
    assert "line 49" in tool_result


@pytest.mark.parametrize("name", ["write_file", "edit_file"])
def test_new_tools_are_registered(name):
    assert name in registry.TOOLS
