"""Step 03: the model may now propose a shell command, and we run it.

Single shot on purpose: we execute what it asked for, put the output in the
transcript, and hand the prompt back to you. The model does not get to react
until you type again. Step 05 turns this into a loop.
"""
import argparse
import json
import sys

import openai

from . import llm, tools

SYSTEM = (
    "You are nanoharness, a coding assistant working in the user's project directory. "
    "You have a bash tool; use it to look at real files instead of guessing."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 03: chat with one bash tool.")
    parser.parse_args(argv)

    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    print(f"nanoharness step03 | {cfg['provider']} | {cfg['model']} | tools: bash | /exit to quit")
    transcript: list[dict] = [{"role": "system", "content": SYSTEM}]

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

        transcript.append({"role": "user", "content": line})
        try:
            reply, usage = llm.chat(transcript, tools=[tools.BASH_SCHEMA])
        except openai.APIError as err:
            transcript.pop()
            print(f"[api error] {err}")
            continue

        transcript.append(reply)
        if reply["content"]:
            print(f"\n{reply['content']}")

        for call in reply.get("tool_calls") or []:
            arguments = json.loads(call["function"]["arguments"] or "{}")
            command = arguments["command"]
            print(f"\n[bash] $ {command}")
            output = tools.run_bash(command)
            print(output)
            # The result goes back as its own message, tied to the call by id.
            transcript.append({"role": "tool", "tool_call_id": call["id"], "content": output})
            print("[the model has not seen this yet - ask it a follow-up question]")

        print(f"[{len(transcript)} messages in memory | {llm.format_usage(usage)}]")

    return 0
