"""Offline test for step 14: a throwaway context with read-only tools."""
import copy
import io
import json

import pytest
from rich.console import Console

from nanoharness import llm, registry, subagent
from nanoharness.agent import Agent
from nanoharness.ui import UI


def quiet_ui(buffer=None):
    return UI(console=Console(file=buffer or io.StringIO(), width=100, force_terminal=False))


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
        self.toolsets = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        self.toolsets.append(sorted(t["function"]["name"] for t in tools or []))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 0, "cost": 0.0}


@pytest.fixture
def project(tmp_path):
    (tmp_path / "auth.py").write_text("def login():\n    return retry(3)\n")
    return tmp_path


def test_task_runs_a_child_and_returns_only_its_answer(project, monkeypatch):
    fake = FakeLLM(
        calls(("c1", "task", {"description": "find the retry", "prompt": "Where is retry used?"})),
        # ---- the child's turn: one tool call, then its answer ----
        calls(("c2", "read_file", {"path": "auth.py"})),
        says("retry(3) is called in auth.py line 2"),
        # ---- back in the parent ----
        says("The retry lives in auth.py."),
    )
    monkeypatch.setattr(llm, "chat", fake)
    parent = Agent(root=project, ui=quiet_ui())
    answer = parent.run("where is the retry logic?")

    assert answer == "The retry lives in auth.py."
    result = [m for m in parent.messages if m["role"] == "tool"][0]["content"]
    assert result == "retry(3) is called in auth.py line 2"
    # The child's file reading never entered the parent transcript.
    assert all("def login" not in str(m.get("content")) for m in parent.messages)
    assert len(parent.messages) == 4


def test_child_starts_with_an_empty_transcript(project, monkeypatch):
    fake = FakeLLM(
        calls(("c1", "task", {"description": "look around", "prompt": "List the files."})),
        says("auth.py"),
        says("done"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    parent = Agent(root=project, ui=quiet_ui())
    parent.run("secret parent context that must not leak")

    child_request = fake.requests[1]
    assert [m["role"] for m in child_request] == ["system", "user", "user"]  # system, prompt, environment
    assert child_request[1]["content"] == "List the files."
    assert "secret parent context" not in json.dumps(child_request)
    assert "You are a subagent" in child_request[0]["content"]


def test_child_toolset_has_no_recursion_and_no_writes(project, monkeypatch):
    fake = FakeLLM(
        calls(("c1", "task", {"description": "look", "prompt": "look"})),
        says("looked"),
        says("done"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    Agent(root=project, ui=quiet_ui()).run("delegate")

    parent_tools, child_tools = fake.toolsets[0], fake.toolsets[1]
    assert "task" in parent_tools and "write_file" in parent_tools
    assert child_tools == ["bash", "list_dir", "load_skill", "read_file"]
    assert "task" not in child_tools and "write_todos" not in child_tools


def test_a_child_that_invents_a_tool_name_is_refused(project):
    parent = Agent(root=project, ui=quiet_ui())
    child = parent.spawn_child(tools=list(subagent.SUBAGENT_TOOLS), note=subagent.SUBAGENT_NOTE)
    result = child.gated_run("write_file", json.dumps({"path": "x.py", "content": "hacked"}))
    assert result.startswith("Error: the tool 'write_file' is not available here")
    assert not (project / "x.py").exists()


def test_child_policy_never_asks(project):
    parent = Agent(root=project, ui=quiet_ui(), approve=lambda *a: pytest.fail("a subagent asked the user"))
    child = parent.spawn_child(tools=list(subagent.SUBAGENT_TOOLS), note=subagent.SUBAGENT_NOTE)
    assert child.policy.mode == "read-only"
    assert child.gated_run("bash", json.dumps({"command": "rm -rf build"})).startswith("Permission denied")
    assert "[exit code 0]" in child.gated_run("bash", json.dumps({"command": "ls"}))


def test_child_shares_root_sandbox_and_ui_console(project):
    parent = Agent(root=project, ui=quiet_ui(), sandbox="none")
    child = parent.spawn_child(tools=["read_file"], note="note")
    assert child.root == parent.root
    assert child.sandbox == parent.sandbox
    assert child.session is None  # nothing to resume: the context is thrown away
    assert child.ui.console is parent.ui.console
    assert child.ui.indent > parent.ui.indent


def test_subagent_output_is_indented(project, monkeypatch):
    buffer = io.StringIO()
    fake = FakeLLM(
        calls(("c1", "task", {"description": "peek at auth", "prompt": "peek"})),
        says("peeked"),
        says("done"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    Agent(root=project, ui=quiet_ui(buffer)).run("delegate")
    text = buffer.getvalue()
    assert "> subagent: peek at auth" in text
    assert "subagent finished: peek at auth" in text


def test_task_without_an_agent_is_an_error():
    assert registry.run_tool("task", json.dumps({"description": "x", "prompt": "y"})).startswith(
        "Error: the task tool can only run inside an agent"
    )


def test_task_schema_hides_the_injected_agent():
    parameters = registry.TOOLS["task"]["schema"]["function"]["parameters"]
    assert sorted(parameters["properties"]) == ["description", "prompt"]
    assert sorted(parameters["required"]) == ["description", "prompt"]
