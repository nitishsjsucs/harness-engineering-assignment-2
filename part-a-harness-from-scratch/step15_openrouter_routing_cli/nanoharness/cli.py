"""Step 15: the installed command. `nanoharness` anywhere, not `python -m` here."""
import argparse
import sys
from pathlib import Path

import openai

from . import __version__, commands, llm, permissions, sandbox as sandbox_module, session as session_module
from .agent import Agent
from .ui import UI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanoharness",
        description="A small coding agent: tools, skills, sessions, permissions, a sandbox and subagents.",
        epilog="Environment: OPENROUTER_API_KEY, HARNESS_MODEL, HARNESS_FALLBACK_MODELS, HARNESS_PROVIDER.",
    )
    parser.add_argument("--version", action="version", version=f"nanoharness {__version__}")
    parser.add_argument("--model", metavar="ID", help="model id for this run, e.g. deepseek/deepseek-v4-pro")
    parser.add_argument("--resume", action="store_true", help="continue the most recent session in this project")
    parser.add_argument("--session", metavar="ID", help="continue a specific session (an id prefix is enough)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--yolo", action="store_true", help="allow everything except the deny list (no prompts)")
    modes.add_argument("--read-only", action="store_true", dest="read_only",
                       help="refuse every write and every command that is not on the read-only allow list")
    parser.add_argument("--no-sandbox", action="store_true", help="run shell commands without the kernel sandbox")
    parser.add_argument("--no-stream", action="store_true", help="wait for the whole reply instead of streaming it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    model = args.model or cfg["model"]
    kind = sandbox_module.NONE if args.no_sandbox else sandbox_module.detect()
    agent = Agent(
        root=root,
        ui=ui,
        session=current,
        policy=permissions.Policy(root, mode),
        sandbox=kind,
        model=model,
        stream=not args.no_stream,
    )
    if resumed is None:
        current.record("meta", cwd=str(root), model=model, provider=cfg["provider"])
    else:
        restored = current.replay()
        agent.load(restored.messages, restored.summary)

    ui.banner(f"nanoharness {__version__} | {cfg['provider']} | {model} | permissions: {mode}")
    ui.info(f"project: {agent.root}")
    ui.info(f"fallbacks: {', '.join(llm.fallback_models(model)) or 'none'}")
    ui.info(f"sandbox: {sandbox_module.describe(kind)}")
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
    total = agent.ledger.total
    spent = f"${total:.6f}" if total is not None else "n/a (this provider reports no cost)"
    ui.info(f"this session cost {spent} over {len(agent.ledger.calls)} model calls")
    return 0
