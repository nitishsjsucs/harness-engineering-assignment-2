"""Slash commands: handled by the harness, never sent to the model.

Anything starting with "/" is ours. That includes typos: an unknown command is
reported here rather than quietly becoming a question to the model.
"""
from . import compaction, llm, session as session_module

COMMANDS: dict[str, dict] = {}


class Exit(Exception):
    """Raised by /exit to leave the REPL."""


def command(name: str, help_text: str):
    def register(handler):
        COMMANDS[name] = {"help": help_text, "run": handler}
        return handler

    return register


def dispatch(line: str, agent, ui) -> bool:
    """Return True if the line was a command (so the REPL must not send it on)."""
    if not line.startswith("/"):
        return False
    name, _, argument = line.partition(" ")
    entry = COMMANDS.get(name)
    if entry is None:
        ui.error(f"unknown command {name}. Try /help.")
        return True
    entry["run"](agent, ui, argument.strip())
    return True


@command("/help", "list the commands")
def _help(agent, ui, argument):
    for name, entry in COMMANDS.items():
        ui.info(f"  {name:<12} {entry['help']}")


@command("/exit", "quit nanoharness")
def _exit(agent, ui, argument):
    raise Exit


@command("/clear", "start a fresh session with an empty transcript")
def _clear(agent, ui, argument):
    agent.messages = []
    agent.todos = []
    agent.session = session_module.Session.new(agent.root)  # the old log stays on disk, resumable
    ui.info(f"cleared; new session {agent.session.id}")


@command("/sessions", "list recent sessions in this project")
def _sessions(agent, ui, argument):
    sessions = session_module.list_sessions(agent.root)
    if not sessions:
        ui.info("no sessions recorded yet")
        return
    for entry in sessions:
        summary = entry.summary()
        current = " (current)" if agent.session and entry.id == agent.session.id else ""
        ui.info(f"  {summary['id']}  {summary['when']}  {summary['messages']:>3} msgs  {summary['first']}{current}")
    ui.info("resume one with /resume <id> or start nanoharness with --session <id>")


@command("/resume", "load another session: /resume <id>")
def _resume(agent, ui, argument):
    if not argument:
        ui.error("usage: /resume <id> (see /sessions)")
        return
    found = session_module.find(agent.root, argument)
    if found is None:
        ui.error(f"no session starting with {argument!r}")
        return
    agent.session = found
    restored = found.replay()
    agent.load(restored.messages, restored.summary)
    ui.info(f"resumed {found.id} with {len(agent.messages)} messages")


@command("/compact", "summarise the older messages to free up context")
def _compact(agent, ui, argument):
    before = compaction.estimate_tokens(agent.request())
    summary = compaction.compact(agent, force=True)
    if summary is None:
        ui.info("nothing older than the current turn to compact yet")
        return
    after = compaction.estimate_tokens(agent.request())
    ui.info(f"about {before} -> {after} estimated tokens")
    ui.info(summary[:400] + ("..." if len(summary) > 400 else ""))


@command("/cost", "what this session has cost so far, by model")
def _cost(agent, ui, argument):
    if not agent.ledger.calls:
        ui.info("no model calls yet")
        return
    for line in agent.ledger.table():
        ui.info(line)


@command("/model", "show the model, or switch it: /model deepseek/deepseek-v4-pro")
def _model(agent, ui, argument):
    if not argument:
        ui.info(f"model: {agent.model or '(provider default)'}")
        ui.info(f"fallbacks: {', '.join(llm.fallback_models(agent.model)) or 'none'}")
        return
    agent.model = argument.strip()
    # The transcript is model-independent, so the next call simply uses the new one.
    ui.info(f"model is now {agent.model}")


@command("/rewind", "drop the last user turn: /rewind [n]")
def _rewind(agent, ui, argument):
    count = int(argument) if argument.isdigit() and int(argument) > 0 else 1
    index = nth_last_user_turn(agent.messages, count)
    if index is None:
        ui.error(f"there are fewer than {count} user turns to rewind")
        return
    dropped = len(agent.messages) - index
    prompt_text = str(agent.messages[index].get("content", ""))[:60]
    del agent.messages[index:]
    if agent.session:
        # Append-only: we record the intent, we never edit the file.
        agent.session.record("rewind", keep=index)
    ui.info(f"rewound {count} turn(s): {dropped} messages dropped (from \"{prompt_text}\")")


def nth_last_user_turn(messages: list[dict], count: int) -> int | None:
    """Index of the user message that starts the n-th turn counted from the end."""
    starts = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if len(starts) < count:
        return None
    return starts[-count]
