"""Offline test for step 13: trimming, the cut rule, and summaries in the prefix."""
import copy
import io
import json

import pytest
from rich.console import Console

from nanoharness import commands, compaction, llm, session as session_module
from nanoharness.agent import Agent
from nanoharness.ui import UI


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
    """Scripted model. Requests made without tools are summariser calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.toolless_requests = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        if not tools:
            self.toolless_requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 0, "cost": 0.0}


def conversation(turns=3, result_chars=2000):
    """turns * (user, assistant with a tool call, tool result, assistant answer)."""
    messages = []
    for index in range(turns):
        messages.append({"role": "user", "content": f"question {index}"})
        messages.append(calls((f"c{index}", "read_file", {"path": f"file{index}.py"})))
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": "x" * result_chars})
        messages.append(says(f"answer {index}"))
    return messages


def test_estimate_grows_with_the_transcript():
    small = compaction.estimate_tokens(conversation(1, 100))
    large = compaction.estimate_tokens(conversation(5, 100))
    assert 0 < small < large


def test_trimming_spares_the_current_turn():
    messages = conversation(3)
    trimmed = compaction.trim_old_tool_results(messages)
    assert trimmed == 2  # the first two turns
    assert messages[2]["content"].startswith("[2000 characters of tool output")
    assert messages[6]["content"].startswith("[2000 characters")
    assert messages[10]["content"] == "x" * 2000  # the most recent turn is untouched
    # Trimming is idempotent and never changes the shape of the transcript.
    assert compaction.trim_old_tool_results(messages) == 0
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"] * 3


def test_short_results_are_left_alone():
    messages = conversation(3, result_chars=10)
    assert compaction.trim_old_tool_results(messages) == 0


def test_cut_is_always_at_a_user_message():
    messages = conversation(3)
    cut = compaction.turn_start(messages, compaction.KEEP_RECENT_TURNS)
    assert messages[cut]["role"] == "user"
    assert cut == 8
    # One turn only: nothing to cut, so nothing is summarised.
    assert compaction.turn_start(conversation(1), 1) is None


def test_compaction_folds_the_summary_into_the_system_prompt(tmp_path, monkeypatch):
    fake = FakeLLM(says("GOAL: fix the parser. FACTS: ..."))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.messages = conversation(3)

    summary = compaction.compact(agent, force=True)
    assert summary.startswith("GOAL:")
    assert agent.summary == summary
    assert len(agent.messages) == 4 and agent.messages[0]["content"] == "question 2"
    assert "Summary of the earlier part" in agent.system_text()
    assert agent.request()[0]["content"].endswith(summary)

    # The summariser ran without tools, and got readable text, not raw messages.
    assert len(fake.toolless_requests) == 1
    prompt_text = fake.toolless_requests[0][1]["content"]
    assert "assistant called read_file" in prompt_text
    assert "question 0" in prompt_text


def test_nothing_happens_below_the_threshold(tmp_path, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.messages = conversation(3)
    assert compaction.compact(agent) is None
    assert fake.requests == []  # no summariser call, no cost


def test_compaction_triggers_automatically_over_budget(tmp_path, monkeypatch):
    # A tiny window, so that trimming alone is not enough to get back under it.
    monkeypatch.setattr(compaction, "CONTEXT_WINDOW", 1000)
    fake = FakeLLM(says("SUMMARY"), says("final answer"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.messages = conversation(4, result_chars=4000)

    agent.run("what now?")
    assert agent.summary == "SUMMARY"
    assert len(fake.toolless_requests) == 1
    assert agent.messages[-1]["content"] == "final answer"


def test_summary_survives_a_resume(tmp_path, monkeypatch):
    fake = FakeLLM(says("one"), says("two"), says("SUMMARY TEXT"))
    monkeypatch.setattr(llm, "chat", fake)
    current = session_module.Session.new(tmp_path)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=current)
    agent.run("first")
    agent.run("second")
    compaction.compact(agent, force=True)

    restored = session_module.Session(current.path).replay()
    assert restored.summary == "SUMMARY TEXT"
    assert restored.messages == agent.messages  # the log applies the same cut


def test_compact_command(tmp_path, monkeypatch):
    fake = FakeLLM(says("SHORT SUMMARY"))
    monkeypatch.setattr(llm, "chat", fake)
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.messages = conversation(2)

    buffer = io.StringIO()
    ui = UI(console=Console(file=buffer, width=120, force_terminal=False))
    assert commands.dispatch("/compact", agent, ui) is True
    assert agent.summary == "SHORT SUMMARY"
    assert "estimated tokens" in buffer.getvalue()


def test_compact_command_on_a_fresh_session_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM())
    agent = Agent(root=tmp_path, ui=quiet_ui())
    buffer = io.StringIO()
    ui = UI(console=Console(file=buffer, width=120, force_terminal=False))
    commands.dispatch("/compact", agent, ui)
    assert "nothing older" in buffer.getvalue()


def test_transcript_text_truncates_huge_results():
    text = compaction.transcript_text(conversation(1, result_chars=5000), result_limit=100)
    assert "tool result: " + "x" * 100 in text
    assert "x" * 200 not in text
