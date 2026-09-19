"""Offline test for step 02: the SDK client is faked, the transcript is real."""
import copy
import types

import pytest

from nanoharness import cli, llm


def fake_response(content, *, cost=0.00002, cached=3):
    """A stand-in for what client.chat.completions.create() returns."""
    message = types.SimpleNamespace(content=content, tool_calls=None, reasoning="secret thoughts")
    usage = types.SimpleNamespace(
        model_dump=lambda: {
            "prompt_tokens": 11,
            "completion_tokens": 4,
            "prompt_tokens_details": {"cached_tokens": cached},
            "cost": cost,
        }
    )
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)


class FakeClient:
    """Records every request and replies from a script."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # deep copy: the REPL keeps appending to the same list object
        self.requests.append(copy.deepcopy(kwargs))
        return fake_response(self.replies.pop(0))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("HARNESS_PROVIDER", "HARNESS_MODEL", "HARNESS_BASE_URL", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    real_connect = llm.connect
    real_connect.cache_clear()
    yield
    real_connect.cache_clear()


def test_openrouter_is_the_default_route():
    settings = llm.settings()
    assert settings["provider"] == "openrouter"
    assert settings["base_url"].startswith("https://openrouter.ai")
    assert settings["model"] == "google/gemini-3.5-flash"


def test_gemini_route_goes_straight_to_google(monkeypatch):
    monkeypatch.setenv("HARNESS_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("HARNESS_MODEL", "google/gemini-3.5-flash")
    direct = llm.settings()
    assert "generativelanguage.googleapis.com" in direct["base_url"]
    assert direct["model"] == "gemini-3.5-flash"  # the "google/" prefix is OpenRouter-only


def test_openai_route_uses_its_own_key_and_default_model(monkeypatch):
    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    settings = llm.settings()
    assert settings["base_url"] == "https://api.openai.com/v1"
    assert settings["api_key"] == "sk-proj-test"
    assert settings["model"] == "gpt-5-mini"


def test_openai_route_keeps_the_model_id_verbatim(monkeypatch):
    """Only the Google route rewrites ids; "gpt-5-mini" must survive untouched."""
    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    monkeypatch.setenv("HARNESS_MODEL", "gpt-4.1-mini")
    assert llm.settings()["model"] == "gpt-4.1-mini"


def test_base_url_override_works_for_every_route(monkeypatch):
    """A gateway, a proxy or a local server can stand in for any provider."""
    monkeypatch.setenv("HARNESS_BASE_URL", "https://gateway.internal/v1")
    assert llm.settings()["base_url"] == "https://gateway.internal/v1"
    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    assert llm.settings()["base_url"] == "https://gateway.internal/v1"


def test_unknown_provider_lists_the_real_ones(monkeypatch):
    monkeypatch.setenv("HARNESS_PROVIDER", "anthropic")
    with pytest.raises(llm.ConfigError) as err:
        llm.settings()
    assert "['gemini', 'openai', 'openrouter']" in str(err.value)


def test_missing_key_names_the_variable_for_that_route(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.ConfigError) as err:
        llm.settings()
    assert "OPENROUTER_API_KEY" in str(err.value)

    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    with pytest.raises(llm.ConfigError) as err:
        llm.settings()
    assert "OPENAI_API_KEY" in str(err.value) and "'openai'" in str(err.value)


def test_missing_key_exits_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert cli.main([]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_to_transcript_keeps_only_resendable_fields():
    message = types.SimpleNamespace(content="hi", tool_calls=None, reasoning="chain of thought", refusal=None)
    assert llm.to_transcript(message) == {"role": "assistant", "content": "hi"}


def test_repl_memory_grows_and_is_resent(monkeypatch, capsys):
    client = FakeClient(["first answer", "second answer"])
    monkeypatch.setattr(llm, "connect", lambda: ({"model": "fake/model", "provider": "openrouter"}, client))

    lines = iter(["what is 2+2?", "and times three?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))

    assert cli.main([]) == 0

    # Turn two resends turn one: user, assistant, user.
    second_request = client.requests[1]["messages"]
    assert [m["role"] for m in second_request] == ["system", "user", "assistant", "user"]
    assert second_request[1]["content"] == "what is 2+2?"
    assert second_request[2] == {"role": "assistant", "content": "first answer"}

    out = capsys.readouterr().out
    assert "second answer" in out
    assert "cost=$0.000020" in out


def test_api_error_does_not_kill_the_repl(monkeypatch, capsys):
    def boom(messages, tools=None):
        raise openai_api_error("upstream is down")

    monkeypatch.setattr(llm, "chat", boom)
    lines = iter(["hello?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert cli.main([]) == 0
    assert "[api error]" in capsys.readouterr().out


def openai_api_error(message):
    import openai

    return openai.APIError(message, request=None, body=None)
