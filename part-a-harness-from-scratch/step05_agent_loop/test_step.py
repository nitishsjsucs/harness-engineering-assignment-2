"""Offline test for step 05: a scripted model drives the loop; no key, no network."""
import copy
import json

import pytest

from nanoharness import agent as agent_module
from nanoharness import llm
from nanoharness.agent import Agent


def says(text):
    return {"role": "assistant", "content": text}


def calls(*specs, content=None):
    """An assistant message asking for one or more tools: calls(("c1", "read_file", {...}))."""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for cid, name, args in specs
        ],
    }


class FakeLLM:
    """Scripted replacement for llm.chat; records every request it is given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 20, "completion_tokens": 5, "cached_tokens": 0, "cost": 0.0}


@pytest.fixture
def fixture_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "notes.txt"
    path.write_text("the answer is 42\n")
    return path


def test_loop_reads_a_file_then_answers(monkeypatch, fixture_file, capsys):
    fake = FakeLLM(
        calls(("call_1", "read_file", {"path": "notes.txt"}), content="Let me check the file."),
        says("The file says the answer is 42."),
    )
    monkeypatch.setattr(llm, "chat", fake)

    agent = Agent()
    answer = agent.run("what does notes.txt say?")

    assert answer == "The file says the answer is 42."
    # The transcript pairs the call with its result, in order.
    assert [m["role"] for m in agent.messages] == ["user", "assistant", "tool", "assistant"]
    assert agent.messages[2]["tool_call_id"] == "call_1"
    assert "the answer is 42" in agent.messages[2]["content"]

    # The second request carried the tool result back to the model.
    second = fake.requests[1]
    assert second[0]["role"] == "system"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"


def test_parallel_tool_calls_answer_every_id_in_order(monkeypatch, fixture_file):
    fake = FakeLLM(
        calls(
            ("a", "read_file", {"path": "notes.txt"}),
            ("b", "list_dir", {"path": "."}),
        ),
        says("both done"),
    )
    monkeypatch.setattr(llm, "chat", fake)

    agent = Agent()
    agent.run("look at two things")
    tool_messages = [m for m in agent.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["a", "b"]


def test_tool_errors_stay_in_the_loop(monkeypatch, fixture_file):
    """A failed tool is an observation, not a crash: the model gets another turn."""
    fake = FakeLLM(
        calls(("c1", "read_file", {"path": "missing.txt"})),
        calls(("c2", "read_file", {"path": "notes.txt"})),
        says("recovered"),
    )
    monkeypatch.setattr(llm, "chat", fake)

    agent = Agent()
    assert agent.run("read the notes") == "recovered"
    assert agent.messages[2]["content"].startswith("Error: read_file failed with FileNotFoundError")
    assert len(fake.requests) == 3


def test_loop_is_bounded(monkeypatch, fixture_file):
    monkeypatch.setattr(agent_module, "MAX_STEPS", 3)
    forever = FakeLLM(*[calls((f"c{i}", "list_dir", {"path": "."})) for i in range(10)])
    monkeypatch.setattr(llm, "chat", forever)

    agent = Agent()
    answer = agent.run("loop forever please")
    assert "stopped after 3 steps" in answer
    assert len(forever.requests) == 3


def test_system_prompt_is_not_stored_in_the_transcript(monkeypatch, fixture_file):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("hi")))
    agent = Agent()
    agent.run("hello")
    assert all(m["role"] != "system" for m in agent.messages)
    assert agent.request()[0]["role"] == "system"


def test_second_turn_keeps_the_first(monkeypatch, fixture_file):
    fake = FakeLLM(says("first"), says("second"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent()
    agent.run("one")
    agent.run("two")
    assert [m["content"] for m in agent.messages] == ["one", "first", "two", "second"]
