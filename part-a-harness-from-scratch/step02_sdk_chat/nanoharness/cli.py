"""Step 02: a multi-turn REPL whose memory is one Python list.

Nothing else remembers anything. Send the list, get a reply, append the reply,
repeat. Delete an element and the model forgets it happened.
"""
import argparse
import sys

import openai

from . import llm

SYSTEM = "You are nanoharness, a concise and practical assistant for a developer."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nanoharness", description="Step 02: multi-turn chat over an OpenAI-compatible API.")
    parser.parse_args(argv)

    try:
        cfg = llm.settings()
    except llm.ConfigError as err:
        print(f"nanoharness: {err}", file=sys.stderr)
        return 2

    print(f"nanoharness step02 | {cfg['provider']} | {cfg['model']} | /exit to quit")

    # The transcript. The system message is just the first element of it.
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
            reply, usage = llm.chat(transcript)
        except openai.APIError as err:
            # Drop the question the model never answered, so the list stays clean.
            transcript.pop()
            print(f"[api error] {err}")
            continue

        transcript.append(reply)
        print(f"\n{reply['content']}")
        print(f"[{len(transcript)} messages in memory | {llm.format_usage(usage)}]")

    print(f"bye ({len(transcript)} messages were in memory; they are gone now)")
    return 0
