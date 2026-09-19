"""Step 10: the REPL, with sessions on disk and slash commands in front of the model."""
import argparse
import sys
from pathlib import Path

import openai

from . import commands, llm, session as session_module
from .agent import Agent
from .ui import UI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 10: an agent with resumable sessions.")
    parser.add_argument("--resume", action="store_true", help="continue the most recent session in this project")
    parser.add_argument("--session", metavar="ID", help="continue a specific session (an id prefix is enough)")
    args = parser.parse_args(argv)

    ui = UI()
    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    root = Path.cwd()
    resumed = None
    if args.session:
        resumed = session_module.find(root, args.session)
        if resumed is None:
            print(f"nanoharness: no session starting with {args.session!r}", file=sys.stderr)
            return 2
    elif args.resume:
        resumed = session_module.latest(root)
        if resumed is None:
            ui.info("no earlier session in this project; starting a new one")

    current = resumed or session_module.Session.new(root)
    agent = Agent(root=root, ui=ui, session=current)
    if resumed is None:
        current.record("meta", cwd=str(root), model=cfg["model"], provider=cfg["provider"])
    else:
        agent.load(current.replay())

    ui.banner(f"nanoharness step10 | {cfg['provider']} | {cfg['model']}")
    ui.info(f"project: {agent.root}")
    ui.info(f"session: {current.id}" + (f" (resumed, {len(agent.messages)} messages)" if resumed else " (new)"))
    ui.info("commands: " + ", ".join(commands.COMMANDS))

    while True:
        try:
            line = ui.ask("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        try:
            if commands.dispatch(line, agent, ui):
                continue  # a command is handled here; the model never sees it
        except commands.Exit:
            break

        try:
            answer = agent.run(line)
        except openai.APIError as err:
            ui.error(f"[api error] {err}")
            continue
        except KeyboardInterrupt:
            ui.error("[interrupted - the transcript is still valid, ask me something else]")
            continue

        ui.answer(answer)

    ui.info(f"session {current.id} saved under {session_module.directory(root)}")
    return 0
