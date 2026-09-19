"""Step 05: the agent loop.

    call the model
      -> append the assistant message (tool calls included)
      -> run each tool, append one role=tool message per call
      -> call the model again
    until the model answers with text instead of tool calls.

That is the entire difference between a chatbot and an agent.
"""
from . import llm, registry
from . import tools  # noqa: F401  importing the module registers the built-in tools

MAX_STEPS = 25  # a bounded loop: a confused model must not burn the account

SYSTEM = (
    "You are nanoharness, a coding agent working in the user's project directory.\n"
    "Use your tools to inspect the real files and run real commands instead of guessing.\n"
    "Work in small steps: look, act, check. When the task is done, reply with a short summary "
    "of what you did and what you found."
)


class Agent:
    """One conversation: a transcript plus the loop that grows it."""

    def __init__(self):
        self.messages: list[dict] = []  # user, assistant and tool messages - no system message
        self.last_usage: dict | None = None

    def request(self) -> list[dict]:
        """What we send. The system prompt is rebuilt every time, never stored."""
        return [{"role": "system", "content": SYSTEM}, *self.messages]

    def run(self, user_text: str) -> str:
        """Run one user turn to completion and return the model's final answer."""
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_STEPS):
            reply, usage = llm.chat(self.request(), tools=registry.schemas())
            self.last_usage = usage
            self.messages.append(reply)
            print(f"[{llm.format_usage(usage)}]")

            calls = reply.get("tool_calls") or []
            if not calls:
                return reply.get("content") or ""

            if reply.get("content"):
                print(f"\n{reply['content']}")
            self.run_tools(calls)

        return f"(stopped after {MAX_STEPS} steps without a final answer)"

    def run_tools(self, calls: list[dict]) -> None:
        """Run every tool call and append its result, keeping ids paired."""
        for index, call in enumerate(calls):
            name = call["function"]["name"]
            raw_arguments = call["function"]["arguments"]
            print(f"\n[{name}] {raw_arguments}")
            try:
                result = registry.run_tool(name, raw_arguments)
            except KeyboardInterrupt:
                # Ctrl-C must still leave a valid transcript: every call needs a result.
                for pending in calls[index:]:
                    self.messages.append(tool_message(pending, "Error: interrupted by the user."))
                raise
            print(preview(result))
            self.messages.append(tool_message(call, result))

    def tool_names(self) -> list[str]:
        return sorted(registry.TOOLS)


def tool_message(call: dict, content: str) -> dict:
    """A tool result is a message of its own, linked by tool_call_id."""
    return {"role": "tool", "tool_call_id": call["id"], "content": content}


def preview(text: str, lines: int = 8) -> str:
    """Terminal output only; the model always gets the full text."""
    rows = text.splitlines()
    if len(rows) <= lines:
        return text
    return "\n".join(rows[:lines] + [f"... ({len(rows) - lines} more lines)"])
