"""The headless proposer: a tool-calling loop that plays the researcher role.

`arh loop` runs this when you have no coding assistant in front of you. It is
deliberately small, because the interesting part is not the agent -- it is that
the agent has no privileges the harness does not grant:

  * write_file / edit_file refuse anything outside [files].editable. The refusal
    is a code path, not a sentence in the prompt.
  * run_experiment is the ONLY way to produce a number, and it returns the
    engine's verdict, including "your edit was reverted".
  * one experiment per episode: each episode starts from a fresh context built
    from the ledger, so the loop can run for hours without the context growing.
    (Harness-books, chapter 5: context is working memory, governed in layers.)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from arh.engine import Harness, HarnessError, format_verdict
from arh.models import BudgetExceeded, Reply, ToolCall

MAX_TOOL_RESULT_CHARS = 8000

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the task directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "path relative to the task directory"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact snippet in an editable file. Preferred over write_file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string", "description": "exact text to replace (must appear once)"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Overwrite an editable file with new content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_experiment",
            "description": (
                "Evaluate the current edit. The harness runs the task command under its budget, "
                "checks the guards, and either commits the change or reverts it. Ends this episode."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "one line: what you changed and the hypothesis behind it",
                    }
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_history",
            "description": "Recent rows of the experiment ledger.",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
]


class TaskTools:
    """The agent's entire surface on the world. Every method returns a string."""

    def __init__(self, harness: Harness):
        self.h = harness
        self.experiments: list[dict] = []
        self._seen: set = set()

    def begin_episode(self) -> None:
        self._seen.clear()

    def dispatch(self, call: ToolCall) -> str:
        handler = getattr(self, call.name, None)
        if handler is None or call.name.startswith("_"):
            return f"ERROR: no such tool {call.name!r}"
        # Anti-loop guard. Weaker models re-read the same frozen file until the
        # episode budget runs out; on a metered API every repeat is a paid
        # request that cannot produce an experiment. Answering the repeat with
        # an instruction costs nothing and breaks the cycle.
        signature = (call.name, json.dumps(call.arguments, sort_keys=True))
        if call.name == "read_file" and signature in self._seen:
            return (
                f"ALREADY READ: {call.arguments.get('path')} is unchanged since you read it in this episode. "
                "Stop reading and act: make ONE change to an editable file with edit_file, "
                "then call run_experiment."
            )
        self._seen.add(signature)
        try:
            return handler(**call.arguments)
        except TypeError as exc:
            return f"ERROR: bad arguments for {call.name}: {exc}"
        except HarnessError as exc:
            return f"ERROR: {exc}"
        except Exception as exc:  # a tool must never kill the loop
            return f"ERROR: {exc.__class__.__name__}: {exc}"

    # -- tools ------------------------------------------------------------
    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"ERROR: {path} does not exist"
        return _truncate(target.read_text(errors="replace"))

    def edit_file(self, path: str, old: str, new: str) -> str:
        target = self._editable(path)
        if isinstance(target, str):
            return target
        text = target.read_text()
        if text.count(old) != 1:
            return f"ERROR: the 'old' snippet appears {text.count(old)} times in {path}; it must appear exactly once"
        target.write_text(text.replace(old, new))
        return f"edited {path}"

    def write_file(self, path: str, content: str) -> str:
        target = self._editable(path)
        if isinstance(target, str):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"wrote {path} ({len(content)} chars)"

    def run_experiment(self, description: str) -> str:
        verdict = self.h.run(description)
        self.experiments.append(verdict)
        return format_verdict(verdict)

    def show_history(self, limit: int = 10) -> str:
        return _truncate(history_table(self.h, int(limit)))

    # -- permission checks ------------------------------------------------
    def _resolve(self, path: str) -> Path:
        target = (self.h.root / path).resolve()
        if not str(target).startswith(str(self.h.root)):
            raise HarnessError(f"{path} is outside the task directory")
        return target

    def _editable(self, path: str):
        target = self._resolve(path)
        rel = target.relative_to(self.h.root).as_posix()
        if not self.h.spec.is_editable(rel):
            return (
                f"DENIED: {rel} is not editable. The harness allows edits only to "
                f"{', '.join(self.h.spec.editable)}. Frozen evaluation code is off limits."
            )
        return target


@dataclass
class LoopResult:
    experiments: list = field(default_factory=list)
    episodes: int = 0
    stopped_because: str = ""
    requests: int = 0
    tokens: int = 0
    cost: float | None = None  # None means the provider does not report a price

    @property
    def kept(self) -> int:
        return sum(1 for v in self.experiments if v["status"] == "keep")


def _log(*args) -> None:
    """Flush every line: a loop that runs for hours is usually watched through
    `tee`, a log file or a CI pane, and a block-buffered pipe shows nothing
    until the process exits."""
    print(*args, flush=True)


def run_loop(
    harness: Harness,
    model,
    max_experiments: int = 10,
    max_seconds: float | None = None,
    max_steps_per_episode: int = 10,
    log=_log,
) -> LoopResult:
    tools = TaskTools(harness)
    result = LoopResult()
    started = time.monotonic()
    stalls = 0

    while len(result.experiments) < max_experiments:
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            result.stopped_because = "time budget reached"
            break
        result.episodes += 1
        log(f"\n[arh] episode {result.episodes}: experiment {len(result.experiments) + 1}/{max_experiments}")
        messages = [
            {"role": "system", "content": system_prompt(harness)},
            {"role": "user", "content": briefing(harness)},
        ]
        tools.begin_episode()
        ran = False
        for _ in range(max_steps_per_episode):
            try:
                reply: Reply = model.complete(messages, TOOL_SCHEMAS)
            except BudgetExceeded as exc:
                # A hard stop, not an error: the cap exists to protect a quota.
                log(f"[arh] {exc}")
                result.stopped_because = str(exc)
                result.experiments = list(tools.experiments)
                return _finalise(result, model)
            messages.append(reply.raw or _assistant_message(reply))
            if not reply.tool_calls:
                if reply.content:
                    log(f"[model] {reply.content.strip()[:400]}")
                break
            for call in reply.tool_calls:
                log(f"[tool] {call.name} {_brief_args(call.arguments)}")
                output = tools.dispatch(call)
                log(f"[tool] -> {output.splitlines()[0][:160] if output else ''}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": _truncate(output)})
                if call.name == "run_experiment" and not output.startswith("ERROR"):
                    ran = True
            if ran:
                break

        if ran:
            stalls = 0
            result.experiments = list(tools.experiments)
            log(format_verdict(result.experiments[-1]))
        else:
            stalls += 1
            log("[arh] episode produced no experiment")
            if stalls >= 3:
                result.stopped_because = "the model stopped proposing experiments"
                break
    else:
        result.stopped_because = "max experiments reached"

    return _finalise(result, model)


def _finalise(result: "LoopResult", model) -> "LoopResult":
    usage = getattr(model, "usage", {})
    result.requests = usage.get("requests", 0)
    result.tokens, result.cost = usage.get("tokens", 0), usage.get("cost")
    return result


def system_prompt(harness: Harness) -> str:
    """The task's program.md is the system prompt (Karpathy's idea), plus the
    facts the harness will enforce anyway -- better to state them up front."""
    spec = harness.spec
    program = harness.root / spec.program
    parts = [program.read_text() if program.is_file() else f"Improve {spec.metric} on task {spec.name}."]
    parts.append(
        "\n---\nHarness facts (enforced in code, not by trust):\n"
        f"- editable files: {', '.join(spec.editable)}. Every other file is frozen; edits to them are refused.\n"
        f"- metric: {spec.metric}, direction {spec.direction}. Only the frozen evaluator may print it.\n"
        f"- each run is killed after {spec.budget_seconds:g}s wall clock.\n"
        "- run_experiment evaluates the working tree and then keeps or reverts it. "
        "A reverted edit is gone: read the verdict before planning the next change.\n"
        "- make ONE focused change per experiment, and say in the description what you expected."
    )
    return "\n".join(parts)


def briefing(harness: Harness) -> str:
    """Fresh context for one episode: state, ledger, current code."""
    s = harness.summary()
    best = s["best"] or {}
    lines = [
        f"Task {s['task']} on branch {s['branch']}.",
        f"Experiments so far: {s['experiments']} (kept {s['counts']['keep']}, discarded {s['counts']['discard']}, "
        f"crashed {s['counts']['crash']}, invalid {s['counts']['invalid']}).",
        f"Baseline {s['metric']}: {(s['baseline'] or {}).get('metric')}. Best so far: {best.get('metric')} "
        f"(experiment {best.get('id')}).",
        "",
        "Recent experiments:",
        history_table(harness, 12),
        "",
        "Current content of the editable files:",
    ]
    for pattern in harness.spec.editable:
        for path in sorted(harness.root.glob(pattern)):
            if path.is_file():
                lines.append(f"\n--- {path.relative_to(harness.root).as_posix()} ---\n{path.read_text(errors='replace')}")
    lines.append("\nPropose ONE change now, apply it with edit_file, then call run_experiment.")
    return _truncate("\n".join(lines), 60000)


def history_table(harness: Harness, limit: int = 10) -> str:
    records = harness.ledger.records()[-limit:]
    if not records:
        return "(no experiments yet)"
    rows = ["id\tstatus\tmetric\tdelta\tdescription\treason"]
    for r in records:
        metric = f"{r['metric']:.6g}" if r["metric"] is not None else "-"
        delta = f"{r['delta']:+.4g}" if r["delta"] is not None else "-"
        rows.append(f"{r['id']}\t{r['status']}\t{metric}\t{delta}\t{r['description']}\t{r.get('reason', '')}")
    return "\n".join(rows)


def _assistant_message(reply: Reply) -> dict:
    message = {"role": "assistant", "content": reply.content}
    if reply.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in reply.tool_calls
        ]
    return message


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} chars truncated by the harness]"


def _brief_args(arguments: dict) -> str:
    return _truncate(json.dumps({k: (v if len(str(v)) < 60 else str(v)[:57] + "...") for k, v in arguments.items()}), 200)
