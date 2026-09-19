"""Offline test for step 15: routing extras, streaming, the cost ledger and packaging."""
import io
import json
import tomllib
import types
from pathlib import Path

import pytest
from rich.console import Console

from nanoharness import __version__, cli, commands, cost, llm
from nanoharness.agent import Agent
from nanoharness.ui import UI


def quiet_ui(buffer=None):
    return UI(console=Console(file=buffer or io.StringIO(), width=120, force_terminal=False))


def chunk(*, text=None, call=None, usage=None, model="google/gemini-3.5-flash"):
    """One streamed chunk, shaped like the SDK's ChatCompletionChunk."""
    tool_calls = None
    if call is not None:
        index, call_id, name, arguments = call
        tool_calls = [
            types.SimpleNamespace(
                index=index, id=call_id, function=types.SimpleNamespace(name=name, arguments=arguments)
            )
        ]
    delta = types.SimpleNamespace(content=text, tool_calls=tool_calls)
    usage_object = None
    if usage is not None:
        usage_object = types.SimpleNamespace(model_dump=lambda: usage)
    return types.SimpleNamespace(
        choices=[] if usage is not None and text is None and call is None else [types.SimpleNamespace(delta=delta)],
        usage=usage_object,
        model=model,
    )


class FakeClient:
    """Records the kwargs of every request and replays a scripted response."""

    def __init__(self, response):
        self.response = response
        self.requests = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("HARNESS_PROVIDER", "HARNESS_MODEL", "HARNESS_BASE_URL", "HARNESS_PROVIDER_SORT",
                 "HARNESS_PROVIDER_ORDER", "HARNESS_FALLBACK_MODELS", "HARNESS_PROVIDER_ALLOW_FALLBACKS",
                 "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    llm.connect.cache_clear()
    yield


def test_default_fallback_is_also_free():
    """Nothing in the default configuration can cost money."""
    assert llm.DEFAULT_FALLBACKS.endswith(":free")
    assert llm.PROVIDERS["openrouter"][2].endswith(":free")
    assert llm.fallback_models("deepseek/deepseek-v4-flash-0731:free") == ["nvidia/nemotron-3.5-lightning:free"]


def test_fallback_chain_is_sent_in_extra_body(monkeypatch):
    monkeypatch.setenv("HARNESS_FALLBACK_MODELS", "deepseek/deepseek-v4-flash, z-ai/glm-5.3-flash")
    client = FakeClient(
        types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hi", tool_calls=None))],
            usage=types.SimpleNamespace(model_dump=lambda: {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.0}),
            model="deepseek/deepseek-v4-flash",
        )
    )
    monkeypatch.setattr(llm, "connect", lambda: ({"provider": "openrouter", "model": "google/gemini-3.5-flash"}, client))

    message, usage = llm.chat([{"role": "user", "content": "hi"}])
    body = client.requests[0]["extra_body"]
    assert body["models"] == ["google/gemini-3.5-flash", "deepseek/deepseek-v4-flash", "z-ai/glm-5.3-flash"]
    assert message == {"role": "assistant", "content": "hi"}
    # The usage says who actually answered, which is not always the first choice.
    assert usage["model"] == "deepseek/deepseek-v4-flash"


def test_provider_preferences_are_optional(monkeypatch):
    assert llm.provider_preferences() == {}
    monkeypatch.setenv("HARNESS_PROVIDER_SORT", "price")
    monkeypatch.setenv("HARNESS_PROVIDER_ORDER", "google-vertex, google-ai-studio")
    monkeypatch.setenv("HARNESS_PROVIDER_ALLOW_FALLBACKS", "0")
    assert llm.provider_preferences() == {
        "sort": "price",
        "order": ["google-vertex", "google-ai-studio"],
        "allow_fallbacks": False,
    }


def test_no_openrouter_extras_for_a_direct_provider(monkeypatch):
    """models/provider are OpenRouter extensions; OpenAI and Google reject unknown keys."""
    monkeypatch.setenv("HARNESS_FALLBACK_MODELS", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("HARNESS_PROVIDER_SORT", "price")
    assert llm.extra_body({"provider": "gemini"}, "gemini-3.5-flash") == {}
    assert llm.extra_body({"provider": "openai"}, "gpt-5-mini") == {}
    assert llm.extra_body({"provider": "openrouter"}, "google/gemini-3.5-flash") != {}


def test_openai_route_is_sent_without_extra_body(monkeypatch):
    client = FakeClient(
        types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hi", tool_calls=None))],
            usage=types.SimpleNamespace(
                model_dump=lambda: {"prompt_tokens": 9, "completion_tokens": 2,
                                    "prompt_tokens_details": {"cached_tokens": 0}}
            ),
            model="gpt-5-mini",
        )
    )
    monkeypatch.setattr(llm, "connect", lambda: ({"provider": "openai", "model": "gpt-5-mini"}, client))
    _message, usage = llm.chat([{"role": "user", "content": "hi"}])
    assert "extra_body" not in client.requests[0]
    assert usage["cost"] is None  # OpenAI never reports a price
    assert usage["cached_tokens"] == 0 and usage["model"] == "gpt-5-mini"


def test_unreported_cached_tokens_stay_none(monkeypatch):
    """A provider that sends no prompt_tokens_details did not say "zero cached"."""
    client = FakeClient(
        types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hi", tool_calls=None))],
            usage=types.SimpleNamespace(model_dump=lambda: {"prompt_tokens": 9, "completion_tokens": 2}),
            model="some/model",
        )
    )
    monkeypatch.setattr(llm, "connect", lambda: ({"provider": "openai", "model": "some/model"}, client))
    _message, usage = llm.chat([{"role": "user", "content": "hi"}])
    assert usage["cached_tokens"] is None

    buffer = io.StringIO()
    quiet_ui(buffer).usage(usage)
    line = buffer.getvalue()
    assert "cached" not in line and "cost=n/a" in line


def test_streaming_assembles_text_and_tool_calls(monkeypatch):
    streamed = [
        chunk(text="Let me "),
        chunk(text="look."),
        chunk(call=(0, "call_1", "read_file", '{"path": ')),
        chunk(call=(0, None, None, '"a.py"}')),
        chunk(usage={"prompt_tokens": 11, "completion_tokens": 4,
                     "prompt_tokens_details": {"cached_tokens": 8}, "cost": 0.00007}),
    ]
    client = FakeClient(iter(streamed))
    monkeypatch.setattr(llm, "connect", lambda: ({"provider": "openrouter", "model": "m"}, client))

    seen = []
    message, usage = llm.chat([{"role": "user", "content": "hi"}], on_text=seen.append)

    assert seen == ["Let me ", "look."]  # the user saw it arrive
    assert message["content"] == "Let me look."
    assert message["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
    ]
    assert client.requests[0]["stream"] is True
    assert client.requests[0]["stream_options"] == {"include_usage": True}
    assert usage["cost"] == 0.00007 and usage["cached_tokens"] == 8


def test_ledger_groups_by_model_and_totals():
    ledger = cost.Ledger()
    ledger.record({"model": "a/one", "prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 40, "cost": 0.001})
    ledger.record({"model": "a/one", "prompt_tokens": 200, "completion_tokens": 20, "cached_tokens": 0, "cost": 0.002})
    ledger.record({"model": "b/two", "prompt_tokens": 50, "completion_tokens": 5, "cached_tokens": 0, "cost": None})

    rows = ledger.by_model()
    assert rows["a/one"] == {"calls": 2, "prompt_tokens": 300, "completion_tokens": 30, "cached_tokens": 40, "cost": 0.003}
    assert rows["b/two"]["cost"] is None  # not zero: that provider never told us
    assert ledger.total == pytest.approx(0.003)
    table = "\n".join(ledger.table())
    assert "total" in table and "n/a" in table
    assert "1 call(s) reported no cost" in table


def test_ledger_on_a_provider_that_prices_nothing():
    ledger = cost.Ledger()
    ledger.record({"model": "gpt-5-mini", "prompt_tokens": 1200, "completion_tokens": 40, "cached_tokens": 0, "cost": None})
    ledger.record({"model": "gpt-5-mini", "prompt_tokens": 1800, "completion_tokens": 20, "cached_tokens": 1024, "cost": None})

    assert ledger.total is None  # never 0.0, which would read as "free"
    table = "\n".join(ledger.table())
    assert "3000" in table and "1024" in table  # the token counts are still exact
    assert "this provider reports no cost" in table


def test_agent_records_every_call_and_cost_command_prints_it(tmp_path, monkeypatch):
    def fake_chat(messages, tools=None, model=None, on_text=None):
        return {"role": "assistant", "content": "done"}, {
            "prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 0, "cost": 0.0005, "model": model,
        }

    monkeypatch.setattr(llm, "chat", fake_chat)
    agent = Agent(root=tmp_path, ui=quiet_ui(), model="google/gemini-3.5-flash")
    agent.run("one")
    agent.run("two")
    assert agent.ledger.total == pytest.approx(0.001)

    buffer = io.StringIO()
    ui = quiet_ui(buffer)
    commands.dispatch("/cost", agent, ui)
    assert "google/gemini-3.5-flash" in buffer.getvalue()
    assert "0.001000" in buffer.getvalue()


def test_model_command_switches_the_next_call(tmp_path, monkeypatch):
    used = []

    def fake_chat(messages, tools=None, model=None, on_text=None):
        used.append(model)
        return {"role": "assistant", "content": "ok"}, {"prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0, "cost": 0.0, "model": model}

    monkeypatch.setattr(llm, "chat", fake_chat)
    agent = Agent(root=tmp_path, ui=quiet_ui(), model="google/gemini-3.5-flash")
    agent.run("first")
    commands.dispatch("/model deepseek/deepseek-v4-pro", agent, quiet_ui())
    agent.run("second")
    assert used == ["google/gemini-3.5-flash", "deepseek/deepseek-v4-pro"]
    assert len(agent.messages) == 4  # switching models keeps the transcript


def test_streaming_agent_does_not_print_the_answer_twice(tmp_path, monkeypatch):
    def fake_chat(messages, tools=None, model=None, on_text=None):
        if on_text:
            on_text("streamed answer")
        return {"role": "assistant", "content": "streamed answer"}, {
            "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0, "cost": 0.0, "model": model,
        }

    monkeypatch.setattr(llm, "chat", fake_chat)
    buffer = io.StringIO()
    ui = quiet_ui(buffer)
    agent = Agent(root=tmp_path, ui=ui, stream=True)
    answer = agent.run("hello")
    ui.answer(answer)
    assert buffer.getvalue().count("streamed answer") == 1


def test_usage_line_names_the_model_that_actually_answered():
    buffer = io.StringIO()
    quiet_ui(buffer).usage(
        {"prompt_tokens": 5, "completion_tokens": 1, "cached_tokens": 0, "cost": 0.0, "model": "deepseek/deepseek-v4-flash"},
        expected_model="google/gemini-3.5-flash",
    )
    assert "served by deepseek/deepseek-v4-flash" in buffer.getvalue()


def test_pyproject_installs_a_console_script():
    data = tomllib.loads((Path(__file__).parent / "pyproject.toml").read_text())
    assert data["project"]["name"] == "nanoharness"
    assert data["project"]["version"] == __version__
    assert data["project"]["scripts"]["nanoharness"] == "nanoharness.cli:main"
    assert data["project"]["requires-python"] == ">=3.10"
    for package in ("openai", "rich", "pyyaml"):
        assert any(requirement.startswith(package) for requirement in data["project"]["dependencies"])


def test_help_and_version_work_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])
    assert exit_info.value.code == 0
    assert "--read-only" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_missing_key_still_exits_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert cli.main([]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
