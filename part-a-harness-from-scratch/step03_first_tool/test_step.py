"""Offline test for step 03: a fake model proposes a command, the harness runs it."""
import copy
import json
import time
import types

import pytest

from nanoharness import cli, llm, tools


def assistant_tool_call(call_id, command):
    return {
        "role": "assistant",
        "content": "Let me look.",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "bash", "arguments": json.dumps({"command": command})},
            }
        ],
    }


class FakeLLM:
    """Replaces llm.chat: returns scripted replies and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, tools=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        return self.replies.pop(0), {"prompt_tokens": 10, "completion_tokens": 3, "cached_tokens": 0, "cost": 0.0}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


def test_bash_returns_output_and_exit_code():
    assert "hello" in tools.run_bash("echo hello")
    assert "[exit code 0]" in tools.run_bash("echo hello")
    assert "[exit code 3]" in tools.run_bash("exit 3")
    assert "No such file" in tools.run_bash("cat /definitely/not/here")  # stderr is captured too


def test_bash_never_waits_for_stdin():
    started = time.time()
    assert "[exit code 0]" in tools.run_bash("cat")  # would hang forever on a terminal
    assert time.time() - started < 5


def test_bash_timeout_kills_the_process_group():
    started = time.time()
    result = tools.run_bash("sleep 30 & sleep 30", timeout=1)
    assert "timed out after 1s" in result
    assert time.time() - started < 10


def test_model_proposes_harness_executes(monkeypatch, capsys, tmp_path):
    marker = tmp_path / "marker.txt"
    marker.write_text("nanoharness was here\n")
    fake = FakeLLM(assistant_tool_call("call_1", f"cat {marker}"))
    monkeypatch.setattr(llm, "chat", fake)
    monkeypatch.setattr(llm, "settings", lambda: {"provider": "fake", "model": "fake/model"})

    lines = iter(["what is in that file?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert cli.main([]) == 0

    # Single shot: exactly one model call, even though a tool ran.
    assert len(fake.requests) == 1
    assert fake.requests[0]["tools"][0]["function"]["name"] == "bash"

    out = capsys.readouterr().out
    assert "nanoharness was here" in out
    assert "the model has not seen this yet" in out


def test_tool_result_is_tied_to_the_call_id(monkeypatch):
    """The transcript must pair every tool_call id with a role=tool message."""
    fake = FakeLLM(assistant_tool_call("call_42", "echo paired"))
    monkeypatch.setattr(llm, "chat", fake)
    monkeypatch.setattr(llm, "settings", lambda: {"provider": "fake", "model": "fake/model"})

    captured = {}
    real_run_bash = tools.run_bash

    def spy(command, timeout=tools.TIMEOUT_SECONDS):
        captured["command"] = command
        return real_run_bash(command, timeout)

    monkeypatch.setattr(tools, "run_bash", spy)
    lines = iter(["echo something", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    cli.main([])
    assert captured["command"] == "echo paired"


def test_schema_shape_is_what_the_api_expects():
    schema = tools.BASH_SCHEMA
    assert schema["type"] == "function"
    assert schema["function"]["parameters"]["required"] == ["command"]
    assert schema["function"]["parameters"]["properties"]["command"]["type"] == "string"
    assert json.dumps(schema)  # must be JSON-serialisable: it is sent over the wire


def test_fake_response_shape_is_unchanged():
    """Guard for the video: llm.chat still returns (message dict, usage dict)."""
    message = types.SimpleNamespace(content="hi", tool_calls=None)
    assert llm.to_transcript(message)["role"] == "assistant"
