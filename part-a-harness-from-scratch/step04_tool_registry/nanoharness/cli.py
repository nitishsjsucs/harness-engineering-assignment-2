"""Step 04: the REPL now offers a whole registry of tools.

Still single shot - the model proposes, we run, you ask the follow-up. But every
tool call now goes through `registry.run_tool`, which never raises.
"""
import argparse
import sys

import openai

from . import llm, registry
from . import tools  # noqa: F401  importing the module is what registers the tools

SYSTEM = (
    "You are nanoharness, a coding assistant working in the user's project directory. "
    "Use your tools to look at real files instead of guessing."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 04: chat with a tool registry.")
    parser.parse_args(argv)

    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    tool_names = ", ".join(sorted(registry.TOOLS))
    print(f"nanoharness step04 | {cfg['provider']} | {cfg['model']} | tools: {tool_names} | /exit to quit")
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
            reply, usage = llm.chat(transcript, tools=registry.schemas())
        except openai.APIError as err:
            transcript.pop()
            print(f"[api error] {err}")
            continue

        transcript.append(reply)
        if reply["content"]:
            print(f"\n{reply['content']}")

        for call in reply.get("tool_calls") or []:
            name = call["function"]["name"]
            raw_arguments = call["function"]["arguments"]
            print(f"\n[{name}] {raw_arguments}")
            result = registry.run_tool(name, raw_arguments)
            print(result)
            transcript.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            print("[the model has not seen this yet - ask it a follow-up question]")

        print(f"[{len(transcript)} messages in memory | {llm.format_usage(usage)}]")

    return 0
