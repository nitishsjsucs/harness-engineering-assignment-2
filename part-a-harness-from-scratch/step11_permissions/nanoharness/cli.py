"""Step 11: the REPL, with a permission mode chosen on the command line."""
import argparse
import sys
from pathlib import Path

import openai

from . import commands, llm, permissions, session as session_module
from .agent import Agent
from .ui import UI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 11: an agent that asks before doing anything risky.")
    parser.add_argument("--resume", action="store_true", help="continue the most recent session in this project")
    parser.add_argument("--session", metavar="ID", help="continue a specific session (an id prefix is enough)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--yolo", action="store_true", help="allow everything except the deny list (no prompts)")
    modes.add_argument("--read-only", action="store_true", dest="read_only",
                       help="refuse every write and every command that is not on the read-only allow list")
    args = parser.parse_args(argv)

    mode = permissions.YOLO if args.yolo else permissions.READ_ONLY if args.read_only else permissions.DEFAULT

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
    agent = Agent(root=root, ui=ui, session=current, policy=permissions.Policy(root, mode))
    if resumed is None:
        current.record("meta", cwd=str(root), model=cfg["model"], provider=cfg["provider"])
    else:
        agent.load(current.replay())

    ui.banner(f"nanoharness step11 | {cfg['provider']} | {cfg['model']} | permissions: {mode}")
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
