"""Offline test for step 08: skills are advertised cheaply and loaded on demand."""
import copy
import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from nanoharness import llm, registry, skills
from nanoharness.agent import Agent
from nanoharness.ui import UI

SKILL_TEXT = """---
name: greeter
description: Say hello in the project's house style.
---

# Greeter

Always start with "Ahoy" and end with the current branch name.
"""


def quiet_ui():
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
        return reply, {"prompt_tokens": 50, "completion_tokens": 5, "cached_tokens": 0, "cost": 0.0}


@pytest.fixture
def project(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "greeter"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_TEXT)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_front_matter_is_parsed(project):
    found = skills.discover(project)
    assert set(found) == {"greeter"}
    assert found["greeter"]["description"].startswith("Say hello")
    assert found["greeter"]["body"].startswith("# Greeter")


def test_both_skill_directories_are_searched(tmp_path):
    hidden = tmp_path / ".nanoharness" / "skills" / "private"
    hidden.mkdir(parents=True)
    (hidden / "SKILL.md").write_text("---\nname: private\ndescription: Internal.\n---\nbody\n")
    visible = tmp_path / "skills" / "public"
    visible.mkdir(parents=True)
    (visible / "SKILL.md").write_text("---\nname: public\ndescription: Shared.\n---\nbody\n")
    assert set(skills.discover(tmp_path)) == {"private", "public"}


def test_a_broken_skill_does_not_break_startup(tmp_path):
    bad = tmp_path / "skills" / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody\n")
    assert skills.discover(tmp_path) == {}


def test_only_name_and_description_reach_the_system_prompt(project):
    agent = Agent(root=project, ui=quiet_ui())
    assert "greeter: Say hello in the project's house style." in agent.system
    assert "Ahoy" not in agent.system  # the body is not paid for until it is loaded


def test_load_skill_returns_the_body(project):
    result = registry.run_tool("load_skill", json.dumps({"name": "greeter"}))
    assert "Always start with" in result
    assert str((project / "skills" / "greeter")) in result  # where its files live


def test_unknown_skill_lists_what_exists(project):
    result = registry.run_tool("load_skill", json.dumps({"name": "nope"}))
    assert result.startswith("Error: no skill named 'nope'")
    assert "greeter" in result


def test_agent_loads_a_skill_mid_turn(project, monkeypatch):
    fake = FakeLLM(
        calls(("c1", "load_skill", {"name": "greeter"}), content="This needs the house style."),
        says("Ahoy there."),
    )
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=project, ui=quiet_ui())
    assert agent.run("greet me") == "Ahoy there."

    skill_result = [m for m in agent.messages if m["role"] == "tool"][0]
    assert "Always start with" in skill_result["content"]
    # The body arrived in the transcript, not in the system prompt.
    assert "Always start with" not in agent.system


def test_shipped_example_skills_are_valid():
    here = Path(__file__).parent
    found = skills.discover(here)
    assert {"code-explainer", "test-writer"} <= set(found)
    for skill in found.values():
        assert skill["description"], f"{skill['name']} has no description"
        assert len(skill["body"]) > 200


def test_catalog_is_empty_when_there_are_no_skills(tmp_path):
    assert skills.catalog(skills.discover(tmp_path)) == ""
    assert llm  # the module under test needs no model access at all
