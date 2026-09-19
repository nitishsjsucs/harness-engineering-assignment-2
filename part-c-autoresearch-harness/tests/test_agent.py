"""The headless proposer, driven by a scripted model so it runs offline.

What matters here is not that the agent is clever, but that it cannot step
outside the harness: its file tools refuse frozen paths, and only the engine
decides what a run was worth.
"""

import json

from arh.agent import TaskTools, briefing, run_loop, system_prompt
from arh.models import ChatModel, Reply, ScriptedModel, ToolCall


def call(name, **arguments):
    return ToolCall(id=f"call-{name}", name=name, arguments=arguments)


# ---------------------------------------------------------------- the tools
def test_read_any_file_in_the_task(harness):
    tools = TaskTools(harness)
    assert "TARGET" in tools.dispatch(call("read_file", path="prepare.py"))


def test_edit_an_editable_file(harness):
    tools = TaskTools(harness)
    assert "edited" in tools.dispatch(call("edit_file", path="train.py", old="VALUE = 5.0", new="VALUE = 4.0"))
    assert "VALUE = 4.0" in (harness.root / "train.py").read_text()


def test_editing_a_frozen_file_is_denied_by_the_harness_not_the_prompt(harness):
    tools = TaskTools(harness)
    before = (harness.root / "prepare.py").read_text()
    result = tools.dispatch(call("edit_file", path="prepare.py", old="TARGET = 3.0", new="TARGET = 5.0"))
    assert result.startswith("DENIED")
    assert (harness.root / "prepare.py").read_text() == before


def test_writing_outside_the_task_directory_is_refused(harness):
    tools = TaskTools(harness)
    result = tools.dispatch(call("write_file", path="../escape.py", content="x = 1"))
    assert "outside the task directory" in result
    assert not (harness.root.parent / "escape.py").exists()


def test_an_ambiguous_edit_is_refused(harness):
    tools = TaskTools(harness)
    result = tools.dispatch(call("edit_file", path="train.py", old="report", new="score"))
    assert "appears 2 times" in result


def test_unknown_tool_and_bad_arguments_do_not_crash_the_loop(harness):
    tools = TaskTools(harness)
    assert "no such tool" in tools.dispatch(call("rm_rf"))
    assert "bad arguments" in tools.dispatch(call("read_file", wrong="train.py"))


def test_run_experiment_returns_the_engine_verdict(harness):
    tools = TaskTools(harness)
    tools.dispatch(call("edit_file", path="train.py", old="VALUE = 5.0", new="VALUE = 4.0"))
    out = tools.dispatch(call("run_experiment", description="closer to the target"))
    assert "KEEP" in out and "score=1" in out
    assert tools.experiments[-1]["status"] == "keep"


def test_run_experiment_reports_harness_refusals_as_errors(harness):
    tools = TaskTools(harness)
    assert tools.dispatch(call("run_experiment", description="no edits")).startswith("ERROR")


# ----------------------------------------------------------------- the loop
def test_the_loop_runs_one_experiment_per_episode(harness):
    model = ScriptedModel(
        [
            Reply(tool_calls=[call("edit_file", path="train.py", old="VALUE = 5.0", new="VALUE = 4.0")]),
            Reply(tool_calls=[call("run_experiment", description="closer")]),
            Reply(tool_calls=[call("edit_file", path="train.py", old="VALUE = 4.0", new="VALUE = 9.0")]),
            Reply(tool_calls=[call("run_experiment", description="much further away")]),
        ]
    )
    result = run_loop(harness, model, max_experiments=5, log=lambda *a: None)
    assert [v["status"] for v in result.experiments] == ["keep", "discard"]
    assert result.kept == 1
    assert result.stopped_because == "the model stopped proposing experiments"
    assert "VALUE = 4.0" in (harness.root / "train.py").read_text(), "the discard was reverted"


def test_the_loop_stops_at_the_experiment_budget(harness):
    replies = []
    for value in ("4.0", "3.5", "3.2"):
        replies.append(Reply(tool_calls=[call("write_file", path="train.py", content=_trainer(value))]))
        replies.append(Reply(tool_calls=[call("run_experiment", description=f"value {value}")]))
    result = run_loop(harness, ScriptedModel(replies), max_experiments=2, log=lambda *a: None)
    assert len(result.experiments) == 2 and result.stopped_because == "max experiments reached"


def test_scripted_model_from_an_experiment_script(harness, tmp_path):
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [
                {"description": "closer", "edits": [{"path": "train.py", "old": "VALUE = 5.0", "new": "VALUE = 4.0"}]},
                {"description": "frozen file", "edits": [{"path": "prepare.py", "old": "TARGET = 3.0", "new": "TARGET = 4.0"}]},
            ]
        )
    )
    model = ScriptedModel.from_experiment_script(script)
    result = run_loop(harness, model, max_experiments=5, log=lambda *a: None)
    assert [v["status"] for v in result.experiments] == ["keep"], "the denied edit produced no experiment"
    assert "TARGET = 3.0" in (harness.root / "prepare.py").read_text()


def test_the_prompt_carries_the_program_and_the_rules(harness):
    prompt = system_prompt(harness)
    assert "toy program" in prompt and "editable files: train.py" in prompt
    text = briefing(harness)
    assert "VALUE = 5.0" in text, "the briefing includes the current editable code"
    assert "Recent experiments" in text


# ------------------------------------------------------- the OpenRouter model
class FakeCompletions:
    def __init__(self):
        self.kwargs = None
        self.usage_cost = 0.002  # OpenRouter prices each call; OpenAI does not

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _fake_response(self.usage_cost)


class FakeClient:
    def __init__(self):
        self.chat = type("chat", (), {"completions": FakeCompletions()})()


def _fake_response(cost=0.002):
    function = type("f", (), {"name": "run_experiment", "arguments": '{"description": "try it"}'})()
    tool_call = type("tc", (), {"id": "1", "function": function})()
    message = type(
        "m",
        (),
        {
            "content": "thinking",
            "tool_calls": [tool_call],
            "model_dump": lambda self, exclude_none=True: {"role": "assistant", "content": "thinking"},
        },
    )()
    choice = type("c", (), {"message": message})()
    usage = type("u", (), {"cost": cost, "total_tokens": 1234})()
    return type("r", (), {"choices": [choice], "usage": usage})()


def test_openrouter_plumbing():
    client = FakeClient()
    model = ChatModel(provider="openrouter", model="test/model", fallbacks=["backup/model"], client=client)
    reply = model.complete([{"role": "user", "content": "hi"}], [{"type": "function"}])

    sent = client.chat.completions.kwargs
    assert sent["model"] == "test/model"
    assert sent["extra_body"]["models"] == ["test/model", "backup/model"], "server-side fallback is requested"
    assert "X-Title" in sent["extra_headers"]
    assert reply.tool_calls[0].name == "run_experiment"
    assert reply.tool_calls[0].arguments == {"description": "try it"}
    assert model.usage == {"tokens": 1234, "cost": 0.002}


def test_openai_plumbing_sends_no_openrouter_extras():
    client = FakeClient()
    model = ChatModel(provider="openai", model="gpt-5-mini", client=client)
    model.complete([{"role": "user", "content": "hi"}], [{"type": "function"}])

    sent = client.chat.completions.kwargs
    assert sent["model"] == "gpt-5-mini"
    assert "extra_body" not in sent and "extra_headers" not in sent
    assert model.name == "openai:gpt-5-mini"
    assert model.base_url == "https://api.openai.com/v1"


def test_cost_is_reported_as_unknown_when_the_provider_omits_it():
    """OpenAI returns no price, so the harness must say n/a, not $0.00."""
    client = FakeClient()
    client.chat.completions.usage_cost = None
    model = ChatModel(provider="openai", model="gpt-5-mini", client=client)
    model.complete([{"role": "user", "content": "hi"}], [{"type": "function"}])
    assert model.usage == {"tokens": 1234, "cost": None}


def test_the_provider_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.delenv("HARNESS_BASE_URL", raising=False)
    model = ChatModel(client=FakeClient())
    assert model.name == "openai:gpt-5-mini"


def _trainer(value):
    return f"from prepare import report\n\nVALUE = {value}\n\nreport(VALUE)\n"
