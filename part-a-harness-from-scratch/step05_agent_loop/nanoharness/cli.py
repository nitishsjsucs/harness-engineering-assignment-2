"""Step 05: the REPL hands each line to the agent loop and prints the answer."""
import argparse
import sys

import openai

from . import llm
from .agent import Agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 05: an agent loop with tools.")
    parser.parse_args(argv)

    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    agent = Agent()
    print(
        f"nanoharness step05 | {cfg['provider']} | {cfg['model']} | "
        f"tools: {', '.join(agent.tool_names())} | /exit to quit"
    )

    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "exit", "quit"):
            break

        try:
            answer = agent.run(line)
        except openai.APIError as err:
            print(f"[api error] {err}")
            continue
        except KeyboardInterrupt:
            print("\n[interrupted - the transcript is still valid, ask me something else]")
            continue

        print(f"\n{answer}")

    return 0
