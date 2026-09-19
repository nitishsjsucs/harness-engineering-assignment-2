"""Offline test for step 09: a plan that lives in the harness, not in the chat."""
import copy
import io
import json

import pytest
from rich.console import Console

from nanoharness import llm, prompt, registry, todos
from nanoharness.agent import Agent
from nanoharness.ui import UI

PLAN = [
    {"content": "read the module", "status": "completed"},
    {"content": "fix the bug", "status": "in_progress"},
    {"content": "run the tests", "status": "pending"},
]


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
        self.tools = tools
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 50, "completion_tokens": 5, "cached_tokens": 0, "cost": 0.0}


def test_schema_describes_a_list_of_objects_with_an_enum():
    parameters = registry.TOOLS["write_todos"]["schema"]["function"]["parameters"]
    item = parameters["properties"]["todos"]["items"]
    assert item["type"] == "object"
    assert item["properties"]["status"]["enum"] == ["pending", "in_progress", "completed"]
    assert sorted(item["required"]) == ["content", "status"]


def test_harness_state_is_hidden_from_the_model():
    parameters = registry.TOOLS["write_todos"]["schema"]["function"]["parameters"]
    assert "agent" not in parameters["properties"]
    assert parameters["required"] == ["todos"]


def test_agent_is_injected_and_cannot_be_faked(tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    smuggled = json.dumps({"todos": [{"content": "a", "status": "pending"}], "agent": "not an agent"})
    assert registry.run_tool("write_todos", smuggled, agent=agent).startswith("Plan updated")
    assert agent.todos == [{"content": "a", "status": "pending"}]


@pytest.mark.parametrize(
    "bad, expected",
    [
        ([{"content": "a", "status": "doing"}], "use pending, in_progress or completed"),
        ([{"content": "", "status": "pending"}], "empty content"),
        (
            [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}],
            "exactly one item may be in progress",
        ),
        ("not a list", "must be a list"),
    ],
)
def test_validation_returns_advice_not_exceptions(bad, expected, tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    result = registry.run_tool("write_todos", json.dumps({"todos": bad}), agent=agent)
    assert result.startswith("Error:") and expected in result
    assert agent.todos == []  # a rejected plan changes nothing


def test_plan_rides_in_the_environment_block_not_in_the_transcript(tmp_path, monkeypatch):
    fake = FakeLLM(
        calls(("c1", "write_todos", {"todos": PLAN}), content="Planning."),
        says("all done"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.run("do the three things")

    assert agent.todos == PLAN
    second_request = fake.requests[1]
    environment = second_request[-1]["content"]
    assert "current plan" in environment
    assert "[x] read the module" in environment
    assert "[~] fix the bug" in environment
    assert "[ ] run the tests" in environment
    # Only the tool result mentions the plan inside the transcript; no environment blocks.
    assert all("<environment>" not in str(m.get("content")) for m in agent.messages)


def test_only_the_latest_plan_is_injected(tmp_path, monkeypatch):
    later = [{"content": "fix the bug", "status": "completed"}]
    fake = FakeLLM(
        calls(("c1", "write_todos", {"todos": PLAN})),
        calls(("c2", "write_todos", {"todos": later})),
        says("done"),
    )
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.run("go")
    environment = fake.requests[-1][-1]["content"]
    assert "[x] fix the bug" in environment
    assert "run the tests" not in environment  # the old version is gone, not stacked


def test_render_and_environment_helpers(tmp_path):
    assert todos.render(PLAN).splitlines()[0] == "[x] read the module"
    assert "current plan" in prompt.environment_block(tmp_path, PLAN)
    assert "current plan" not in prompt.environment_block(tmp_path, [])


def test_ui_draws_the_checklist():
    buffer = io.StringIO()
    UI(console=Console(file=buffer, width=100, force_terminal=False)).todos(PLAN)
    text = buffer.getvalue()
    assert "[x] read the module" in text and "[~] fix the bug" in text and "[ ] run the tests" in text
