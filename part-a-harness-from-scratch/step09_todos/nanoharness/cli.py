"""Step 09: the REPL; the agent now keeps a visible plan."""
import argparse
import sys

import openai

from . import llm
from .agent import Agent
from .ui import UI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 09: an agent that plans with a todo list.")
    parser.parse_args(argv)

    ui = UI()
    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    agent = Agent(ui=ui)
    ui.banner(f"nanoharness step09 | {cfg['provider']} | {cfg['model']}")
    ui.info(f"project: {agent.root}")
    ui.info(f"skills: {', '.join(agent.skills) or 'none found'}")
    ui.info(f"tools: {', '.join(agent.tool_names())} | /exit to quit")

    while True:
        try:
            line = ui.ask("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/exit", "exit", "quit"):
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

    return 0
