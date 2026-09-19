"""Offline test for step 07: a stable prefix, and facts injected late."""
import copy
import io
import json
import subprocess

import pytest
from rich.console import Console

from nanoharness import llm, prompt
from nanoharness.agent import Agent
from nanoharness.ui import UI


def quiet_ui():
    return UI(console=Console(file=io.StringIO(), width=100, force_terminal=False))


def says(text):
    return {"role": "assistant", "content": text}


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 100, "completion_tokens": 5, "cached_tokens": 64, "cost": 0.0}


@pytest.fixture
def project(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# House rules\nAlways run pytest before answering.\n")
    return tmp_path


def test_instruction_file_lands_in_the_system_prompt(project):
    text = prompt.system_prompt(project)
    assert text.startswith(prompt.BASE)
    assert "Always run pytest before answering." in text
    assert "AGENTS.md" in text


def test_missing_instruction_file_is_fine(tmp_path):
    assert prompt.system_prompt(tmp_path) == prompt.BASE


def test_environment_block_has_the_volatile_facts(project):
    block = prompt.environment_block(project)
    assert block.startswith("<environment>") and block.endswith("</environment>")
    assert f"cwd: {project}" in block
    assert "now: " in block
    assert "did not type it" in block  # the model must not mistake it for a user message


def test_environment_block_reports_git_state(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    block = prompt.environment_block(tmp_path)
    assert "git branch: trunk" in block
    assert "git status: 1 changed: a.py" in block


def test_environment_block_survives_a_non_git_directory(tmp_path):
    block = prompt.environment_block(tmp_path)
    assert "git branch" not in block  # no repository, no noise


def test_environment_is_in_the_request_but_not_in_the_transcript(monkeypatch, project):
    fake = FakeLLM(says("ok"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=project, ui=quiet_ui())
    agent.run("hello")

    sent = fake.requests[0]
    assert sent[-1]["role"] == "user" and sent[-1]["content"].startswith("<environment>")
    assert sent[0]["role"] == "system" and "House rules" in sent[0]["content"]
    # The transcript keeps only the real conversation.
    assert [m["content"] for m in agent.messages] == ["hello", "ok"]
    assert all("<environment>" not in str(m["content"]) for m in agent.messages)


def test_prefix_is_byte_identical_across_turns(monkeypatch, project):
    """The cache-friendly rule: everything before the new messages must not change."""
    fake = FakeLLM(says("one"), says("two"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=project, ui=quiet_ui())
    agent.run("first")
    agent.run("second")

    first, second = fake.requests
    assert first[0] == second[0]  # identical system message
    assert first[1] == second[1]  # the first user message is untouched in turn two
    assert second[2] == {"role": "assistant", "content": "one"}
    # Only the environment block differs at the end.
    assert first[-1]["content"].startswith("<environment>")
    assert second[-1]["content"].startswith("<environment>")


def test_system_prompt_is_read_once(monkeypatch, project):
    fake = FakeLLM(says("one"), says("two"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=project, ui=quiet_ui())
    agent.run("first")
    (project / "AGENTS.md").write_text("# Changed mid-session\n")
    agent.run("second")
    assert "House rules" in fake.requests[1][0]["content"]  # still the startup version


def test_usage_line_shows_cached_tokens():
    buffer = io.StringIO()
    UI(console=Console(file=buffer, width=100, force_terminal=False)).usage(
        {"prompt_tokens": 1200, "completion_tokens": 30, "cached_tokens": 1024, "cost": 0.0003}
    )
    assert "in=1200 (cached 1024)" in buffer.getvalue()


def test_agent_still_runs_tools(monkeypatch, project):
    fake = FakeLLM(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "list_dir", "arguments": json.dumps({"path": str(project)})}}
            ],
        },
        says("listed"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=project, ui=quiet_ui())
    assert agent.run("list it") == "listed"
    assert "AGENTS.md" in [m for m in agent.messages if m["role"] == "tool"][0]["content"]
