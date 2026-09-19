"""Offline test for step 10: append-only logs, resume, repair and slash commands."""
import copy
import io
import json

import pytest
from rich.console import Console

from nanoharness import cli, commands, llm, session as session_module
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
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else says("done")
        return reply, {"prompt_tokens": 20, "completion_tokens": 3, "cached_tokens": 0, "cost": 0.0}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


def test_every_message_is_logged_as_it_happens(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("hi there")))
    current = session_module.Session.new(tmp_path)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=current)
    agent.run("hello")

    events = current.events()
    assert [e["kind"] for e in events] == ["message", "message"]
    assert events[0]["message"] == {"role": "user", "content": "hello"}
    assert current.path.parent == tmp_path / ".nanoharness" / "sessions"


def test_replay_rebuilds_the_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("one"), says("two")))
    current = session_module.Session.new(tmp_path)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=current)
    agent.run("first")
    agent.run("second")

    revived = session_module.Session(current.path).replay()
    assert revived == agent.messages


def test_rewind_is_an_event_not_a_rewrite(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("one"), says("two")))
    current = session_module.Session.new(tmp_path)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=current)
    agent.run("first")
    agent.run("second")

    commands.dispatch("/rewind", agent, quiet_ui())
    assert [m["content"] for m in agent.messages] == ["first", "one"]
    assert [e["kind"] for e in current.events()] == ["message"] * 4 + ["rewind"]
    assert session_module.Session(current.path).replay() == agent.messages  # replay agrees


def test_rewind_two_turns_and_refuses_too_many(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("one"), says("two")))
    agent = Agent(root=tmp_path, ui=quiet_ui())
    agent.run("first")
    agent.run("second")
    assert commands.dispatch("/rewind 5", agent, quiet_ui()) is True
    assert len(agent.messages) == 4  # refused, nothing dropped
    commands.dispatch("/rewind 2", agent, quiet_ui())
    assert agent.messages == []


def test_repair_answers_interrupted_tool_calls():
    broken = [
        {"role": "user", "content": "go"},
        calls(("c1", "bash", {"command": "sleep 100"}), ("c2", "bash", {"command": "ls"})),
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
    ]
    fixed = session_module.repair(broken)
    assert [m["role"] for m in fixed] == ["user", "assistant", "tool", "tool"]
    assert fixed[-1]["tool_call_id"] == "c1"
    assert "interrupted" in fixed[-1]["content"]
    assert session_module.repair(fixed) == fixed  # repairing twice changes nothing


def test_a_half_written_line_is_skipped(tmp_path):
    current = session_module.Session.new(tmp_path)
    current.record("message", message={"role": "user", "content": "hello"})
    with current.path.open("a") as handle:
        handle.write('{"kind": "message", "message": {"role": "assi')  # killed mid-write
    assert current.replay() == [{"role": "user", "content": "hello"}]


def test_resume_picks_the_latest_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(llm, "chat", FakeLLM(says("remembered")))
    first = session_module.Session.new(tmp_path)
    Agent(root=tmp_path, ui=quiet_ui(), session=first).run("what did I say?")

    lines = iter(["/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    monkeypatch.setattr(UI, "ask", lambda self, label="": next(lines))
    assert cli.main(["--resume"]) == 0
    assert session_module.latest(tmp_path).id == first.id


def test_unknown_session_id_exits_with_a_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--session", "nope"]) == 2
    assert "no session starting with" in capsys.readouterr().err


def test_commands_never_reach_the_model(tmp_path, monkeypatch):
    never = FakeLLM()

    def explode(*args, **kwargs):
        raise AssertionError("a slash command was sent to the model")

    monkeypatch.setattr(llm, "chat", explode)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=session_module.Session.new(tmp_path))
    for line in ["/help", "/sessions", "/clear", "/rewind", "/not-a-command"]:
        assert commands.dispatch(line, agent, quiet_ui()) is True
    assert commands.dispatch("please explain /help", agent, quiet_ui()) is False
    assert never.requests == []


def test_clear_starts_a_new_session_and_keeps_the_old_one(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("one")))
    first = session_module.Session.new(tmp_path)
    agent = Agent(root=tmp_path, ui=quiet_ui(), session=first)
    agent.run("first")

    commands.dispatch("/clear", agent, quiet_ui())
    assert agent.messages == [] and agent.todos == []
    assert agent.session.id != first.id
    assert first.replay()[0]["content"] == "first"  # the old log is untouched


def test_exit_command_raises_exit(tmp_path):
    agent = Agent(root=tmp_path, ui=quiet_ui())
    with pytest.raises(commands.Exit):
        commands.dispatch("/exit", agent, quiet_ui())


def test_sessions_listing_shows_the_first_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", FakeLLM(says("hi")))
    current = session_module.Session.new(tmp_path)
    Agent(root=tmp_path, ui=quiet_ui(), session=current).run("summarise the repo")

    buffer = io.StringIO()
    ui = UI(console=Console(file=buffer, width=120, force_terminal=False))
    commands.dispatch("/sessions", Agent(root=tmp_path, ui=ui, session=current), ui)
    text = buffer.getvalue()
    assert current.id in text and "summarise the repo" in text and "(current)" in text
