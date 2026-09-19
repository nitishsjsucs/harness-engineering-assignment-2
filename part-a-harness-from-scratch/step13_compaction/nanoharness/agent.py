"""Step 08: the same loop; skills put long instructions behind a tool call.

    call the model
      -> append the assistant message (tool calls included)
      -> run each tool, append one role=tool message per call
      -> call the model again
    until the model answers with text instead of tool calls.
"""
from pathlib import Path

from . import compaction, llm, permissions, prompt, registry, sandbox as sandbox_module, skills
from . import todos as todos_module  # noqa: F401  registers write_todos
from . import tools  # noqa: F401  importing the module registers the built-in tools
from .ui import UI, describe

MAX_STEPS = 25  # a bounded loop: a confused model must not burn the account


class Agent:
    """One conversation: a transcript plus the loop that grows it."""

    def __init__(
        self,
        root: Path | str | None = None,
        ui: UI | None = None,
        session=None,
        policy: permissions.Policy | None = None,
        approve=None,
        sandbox: str | None = None,
    ):
        self.root = Path(root or Path.cwd()).resolve()
        self.messages: list[dict] = []  # user, assistant and tool messages - no system message
        self.ui = ui or UI()
        self.last_usage: dict | None = None
        self.todos: list[dict] = []  # the plan lives here, not in the transcript
        self.summary: str | None = None  # set by compaction; folded into the system prompt
        self.session = session  # a session.Session, or None for a throwaway agent
        self.policy = policy or permissions.Policy(self.root)
        # The bash tool reads this through the injected agent parameter.
        self.sandbox = sandbox or sandbox_module.detect()
        # Asking is a UI concern; tests pass a function that answers for them.
        self.approve = approve or self.ui.confirm
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
            {"role": "system", "content": self.system_text()},
            *self.messages,
            {"role": "user", "content": prompt.environment_block(self.root, self.todos)},
        ]

    def system_text(self) -> str:
        """The stable prefix, plus whatever compaction has folded into it."""
        if not self.summary:
            return self.system
        return f"{self.system}\n\n# Summary of the earlier part of this conversation\n{self.summary}"

    def add(self, message: dict) -> None:
        """The only way a message enters the transcript, so the log cannot drift."""
        self.messages.append(message)
        if self.session:
            self.session.record("message", message=message)

    def load(self, messages: list[dict], summary: str | None = None) -> None:
        """Adopt a replayed transcript without writing it to the log again."""
        self.messages = list(messages)
        self.summary = summary

    def run(self, user_text: str) -> str:
        """Run one user turn to completion and return the model's final answer."""
        # A new turn: the previous turn's tool results have done their job.
        compaction.trim_old_tool_results(self.messages)
        self.add({"role": "user", "content": user_text})

        for _ in range(MAX_STEPS):
            compaction.compact(self)  # returns immediately unless we are over budget
            with self.ui.thinking():
                reply, usage = llm.chat(self.request(), tools=registry.schemas())
            self.last_usage = usage
            self.add(reply)
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
                result = self.gated_run(name, raw_arguments)
            except KeyboardInterrupt:
                # Ctrl-C must still leave a valid transcript: every call needs a result.
                for pending in calls[index:]:
                    self.add(tool_message(pending, "Error: interrupted by the user."))
                raise
            if name == "write_todos" and not result.startswith("Error"):
                self.ui.todos(self.todos)
            else:
                self.ui.tool_result(result)
            self.add(tool_message(call, result))

    def gated_run(self, name: str, raw_arguments: str) -> str:
        """Ask the policy first. Every verdict is reported to the model as a result."""
        verdict = self.policy.check(name, raw_arguments)
        if verdict.decision == permissions.DENY:
            self.ui.error(f"denied: {verdict.reason}")
            return (
                f"Permission denied: {verdict.reason}. Do not try this again; "
                "tell the user what you wanted to do and why."
            )
        if verdict.decision == permissions.ASK:
            answer = self.approve(name, describe(name, raw_arguments), verdict.reason)
            if answer == "a":
                remembered = self.policy.remember(name, raw_arguments)
                self.ui.info(f"allowed for this session: {remembered}")
            elif answer != "y":
                return (
                    "The user declined this tool call. Do not repeat it; "
                    "suggest another approach or ask them what to do instead."
                )
        return registry.run_tool(name, raw_arguments, agent=self)

    def tool_names(self) -> list[str]:
        return sorted(registry.TOOLS)


def tool_message(call: dict, content: str) -> dict:
    """A tool result is a message of its own, linked by tool_call_id."""
    return {"role": "tool", "tool_call_id": call["id"], "content": content}
