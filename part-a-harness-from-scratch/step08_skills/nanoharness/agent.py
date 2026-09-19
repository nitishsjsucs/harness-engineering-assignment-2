"""Step 08: the same loop; skills put long instructions behind a tool call.

    call the model
      -> append the assistant message (tool calls included)
      -> run each tool, append one role=tool message per call
      -> call the model again
    until the model answers with text instead of tool calls.
"""
from pathlib import Path

from . import llm, prompt, registry, skills
from . import tools  # noqa: F401  importing the module registers the built-in tools
from .ui import UI

MAX_STEPS = 25  # a bounded loop: a confused model must not burn the account


class Agent:
    """One conversation: a transcript plus the loop that grows it."""

    def __init__(self, root: Path | str | None = None, ui: UI | None = None):
        self.root = Path(root or Path.cwd()).resolve()
        self.messages: list[dict] = []  # user, assistant and tool messages - no system message
        self.ui = ui or UI()
        self.last_usage: dict | None = None
        # Only name and description of each skill are in the prompt; bodies stay on disk.
        self.skills = skills.discover(self.root)
        # Built once: a prefix that changes between calls is a prefix that is never cached.
        self.system = prompt.system_prompt(self.root, extras=[skills.catalog(self.skills)])

    def request(self) -> list[dict]:
        """Stable system prompt, then the transcript, then today's facts.

        The environment block is part of the request only. Storing it would put a
        timestamp in the middle of the transcript and invalidate the cache on
        every future call.
        """
        return [
            {"role": "system", "content": self.system},
            *self.messages,
            {"role": "user", "content": prompt.environment_block(self.root)},
        ]

    def run(self, user_text: str) -> str:
        """Run one user turn to completion and return the model's final answer."""
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_STEPS):
            with self.ui.thinking():
                reply, usage = llm.chat(self.request(), tools=registry.schemas())
            self.last_usage = usage
            self.messages.append(reply)
            self.ui.usage(usage)

            calls = reply.get("tool_calls") or []
            if not calls:
                return reply.get("content") or ""

            self.ui.thought(reply.get("content") or "")
            self.run_tools(calls)

        return f"(stopped after {MAX_STEPS} steps without a final answer)"

    def run_tools(self, calls: list[dict]) -> None:
        """Run every tool call and append its result, keeping ids paired."""
        for index, call in enumerate(calls):
            name = call["function"]["name"]
            raw_arguments = call["function"]["arguments"]
            self.ui.tool_call(name, raw_arguments)
            try:
                result = registry.run_tool(name, raw_arguments)
            except KeyboardInterrupt:
                # Ctrl-C must still leave a valid transcript: every call needs a result.
                for pending in calls[index:]:
                    self.messages.append(tool_message(pending, "Error: interrupted by the user."))
                raise
            self.ui.tool_result(result)
            self.messages.append(tool_message(call, result))

    def tool_names(self) -> list[str]:
        return sorted(registry.TOOLS)


def tool_message(call: dict, content: str) -> dict:
    """A tool result is a message of its own, linked by tool_call_id."""
    return {"role": "tool", "tool_call_id": call["id"], "content": content}
