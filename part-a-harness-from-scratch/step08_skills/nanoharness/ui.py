"""Everything the terminal shows. This module knows nothing about models.

Keeping rendering here means the agent loop stays readable, the UI can be swapped
for a quiet one in tests, and a subagent can later reuse it with an indent.
"""
import json
import sys
from contextlib import contextmanager

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

RESULT_LINES = 8  # how much of a tool result we show; the model always gets all of it


class UI:
    def __init__(self, console: Console | None = None):
        self.console = console or Console(highlight=False)
        self._prompt_session: PromptSession | None = None

    # ----- input -------------------------------------------------------
    def ask(self, label: str = "you> ") -> str:
        """Read one line. prompt_toolkit gives history and line editing on a terminal."""
        if not sys.stdin.isatty():
            return input(label)  # piped input, e.g. `echo /exit | python -m nanoharness`
        if self._prompt_session is None:
            self._prompt_session = PromptSession(history=InMemoryHistory())
        return self._prompt_session.prompt(label)

    # ----- output ------------------------------------------------------
    def banner(self, text: str) -> None:
        self.console.print(Text(text, style="bold magenta"))

    def info(self, text: str) -> None:
        self.console.print(Text(text, style="dim"))

    def error(self, text: str) -> None:
        self.console.print(Text(text, style="bold red"))

    def thought(self, text: str) -> None:
        """Assistant text that came alongside tool calls - a running commentary."""
        if text and text.strip():
            self.console.print(Text(text.strip(), style="italic dim"))

    @contextmanager
    def thinking(self, label: str = "thinking"):
        """A spinner while we wait for the model, so the terminal never looks frozen."""
        status = self.console.status(f"[dim]{label}...", spinner="dots")
        status.start()
        try:
            yield
        finally:
            status.stop()

    def tool_call(self, name: str, arguments: dict | str) -> None:
        self.console.print(
            Panel(
                Text(describe(name, arguments), style="bold"),
                title=f"[cyan]{name}",
                title_align="left",
                border_style="cyan",
            )
        )

    def tool_result(self, text: str, lines: int = RESULT_LINES) -> None:
        rows = text.splitlines()
        shown = rows[:lines]
        if len(rows) > lines:
            shown.append(f"... ({len(rows) - lines} more lines)")
        self.console.print(Text("\n".join(shown) or "(no output)", style="dim"))

    def answer(self, text: str) -> None:
        self.console.print(Markdown(text or "_(empty answer)_"))

    def usage(self, usage: dict) -> None:
        cost = usage.get("cost")
        cost_text = f"${cost:.6f}" if cost is not None else "n/a"
        cached = usage.get("cached_tokens") or 0
        self.console.print(
            Text(
                f"  in={usage['prompt_tokens']} (cached {cached}) "
                f"out={usage['completion_tokens']} cost={cost_text}",
                style="dim",
            )
        )


def describe(name: str, arguments: dict | str) -> str:
    """One readable line per tool call; the raw JSON is rarely what you want to read."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return arguments
    if name == "bash":
        return f"$ {arguments.get('command', '')}"
    if name == "read_file":
        start = arguments.get("offset", 1)
        return f"{arguments.get('path', '?')}" + (f" from line {start}" if start != 1 else "")
    if name == "write_file":
        return f"{arguments.get('path', '?')} ({len(str(arguments.get('content', '')).splitlines())} lines)"
    if name == "edit_file":
        old_lines = str(arguments.get("old_text", "")).strip().splitlines()
        snippet = old_lines[0][:60] if old_lines else ""
        return f"{arguments.get('path', '?')}: replace {snippet!r} ..."
    return json.dumps(arguments, ensure_ascii=False)[:200]
