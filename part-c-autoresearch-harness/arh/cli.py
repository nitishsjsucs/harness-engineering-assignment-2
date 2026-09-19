"""The `arh` command line.

    arh init tasks/quickstart      verify the spec, prepare data, create the branch
    arh baseline                   measure the unmodified code
    arh run -m "what I changed"    evaluate the working tree, keep it or revert it
    arh status                     where the loop stands
    arh guard                      run every guard now, without an experiment
    arh diff                       the pending edit the next run would evaluate
    arh report                     progress.png + report.md
    arh loop --agent openrouter    let a model drive the whole thing

Every command except `init` finds its task by walking up from the current
directory (or from -C), so agents do not have to remember paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from arh import __version__
from arh.engine import Harness, HarnessError, find_task_dir, format_verdict
from arh.spec import SpecError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (HarnessError, SpecError) as exc:
        print(f"arh: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\narh: interrupted", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arh", description="autoresearch harness")
    parser.add_argument("--version", action="version", version=f"arh {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def task_arg(p):
        p.add_argument("-C", "--task", default=None, help="task directory (default: found from cwd)")
        return p

    p = sub.add_parser("init", help="prepare a task: run setup, create the branch, hash frozen files")
    p.add_argument("task_dir")
    p.add_argument("--tag", default=None, help="branch tag; default is today, e.g. autoresearch/sep19")
    p.add_argument(
        "--git-mode",
        choices=("isolated", "repo"),
        default="isolated",
        help="isolated: a private repo under .arh/git (never touches an enclosing repo). "
        "repo: branch inside the repository that already contains the task",
    )
    p.add_argument("--force", action="store_true", help="archive an existing .arh and start over")
    p.set_defaults(func=cmd_init)

    p = task_arg(sub.add_parser("baseline", help="measure the unmodified code"))
    p.add_argument("--stream", action="store_true", help="echo the run's output live")
    p.set_defaults(func=cmd_baseline)

    p = task_arg(sub.add_parser("run", help="evaluate the current edit and keep or revert it"))
    p.add_argument("-m", "--message", required=True, help="what you changed and why")
    p.add_argument("--stream", action="store_true")
    p.add_argument("--json", action="store_true", help="print the ledger record as JSON")
    p.set_defaults(func=cmd_run)

    p = task_arg(sub.add_parser("status", help="branch, best score, recent experiments"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = task_arg(sub.add_parser("guard", help="run every guard now; exit 1 if any fires"))
    p.set_defaults(func=cmd_guard)

    p = task_arg(sub.add_parser("diff", help="the pending edit that the next run would evaluate"))
    p.set_defaults(func=cmd_diff)

    p = task_arg(sub.add_parser("report", help="write progress.png and report.md"))
    p.add_argument("--out", default=None, help="output directory (default: <task>/.arh)")
    p.set_defaults(func=cmd_report)

    p = task_arg(sub.add_parser("loop", help="headless proposer: model + tools + engine"))
    p.add_argument(
        "--agent",
        choices=("llm", "openrouter", "openai", "gemini", "scripted"),
        default="llm",
        help="llm: the provider from HARNESS_PROVIDER (default openrouter). "
        "Naming a provider (openrouter/openai/gemini) overrides it. "
        "scripted: replay a JSON experiment script offline",
    )
    p.add_argument("--script", default=None, help="JSON experiment script for --agent scripted")
    p.add_argument("--max", type=int, default=10, help="experiments to run in this loop")
    p.add_argument("--minutes", type=float, default=None, help="stop after this much wall clock")
    p.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="hard cap on model API calls; a free tier is a daily quota, not a tap",
    )
    p.add_argument("--model", default=None, help="override HARNESS_MODEL")
    p.add_argument("--dry-run", action="store_true", help="print the prompt and tools, call no model")
    p.set_defaults(func=cmd_loop)
    return parser


# ----------------------------------------------------------------- commands
def cmd_init(args) -> int:
    harness = Harness.init(args.task_dir, tag=args.tag, git_mode=args.git_mode, force=args.force)
    spec, state = harness.spec, harness.state
    print(f"initialised task '{spec.name}' in {harness.root}")
    print(f"  branch      {state['branch']}  ({state['git_mode']} git mode)")
    print(f"  editable    {', '.join(spec.editable)}")
    print(f"  frozen      {', '.join(spec.frozen)}  ({len(state['frozen_hashes'])} files hashed)")
    print(f"  metric      {spec.metric} ({spec.direction}), budget {spec.budget_seconds:g}s per run")
    enclosing = harness.git.enclosing_repo()
    if state["git_mode"] == "isolated" and enclosing:
        print(f"  note        this task sits inside {enclosing}; that repository is untouched")
    print("next: arh baseline")
    return 0


def cmd_baseline(args) -> int:
    harness = _harness(args)
    verdict = harness.baseline(stream=args.stream)
    print(format_verdict(verdict))
    return 0


def cmd_run(args) -> int:
    harness = _harness(args)
    verdict = harness.run(args.message, stream=args.stream)
    print(json.dumps(verdict, indent=2) if args.json else format_verdict(verdict))
    return 0


def cmd_status(args) -> int:
    harness = _harness(args)
    summary = harness.summary()
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    best, baseline = summary["best"] or {}, summary["baseline"] or {}
    print(f"task      {summary['task']}  ({summary['metric']}, {summary['direction']})")
    print(f"branch    {summary['branch']}  ({summary['git_mode']})")
    counts = summary["counts"]
    limit = f"/{summary['max_experiments']}" if summary["max_experiments"] else ""
    print(
        f"runs      {summary['experiments']}{limit}  keep {counts['keep']}  discard {counts['discard']}  "
        f"crash {counts['crash']}  invalid {counts['invalid']}"
    )
    if baseline:
        print(f"baseline  {baseline['metric']:.6g}")
    if best:
        print(f"best      {best['metric']:.6g}  (experiment {best['id']}, commit {best['commit'][:7]})")
    print(f"pending   {', '.join(summary['pending_changes']) or 'no edits in the working tree'}")
    if summary["recent"]:
        print("\nrecent experiments:")
        from arh.agent import history_table

        print(history_table(harness, 10))
    return 0


def cmd_guard(args) -> int:
    harness = _harness(args)
    problems = harness.check()
    if not problems:
        print("all guards pass: frozen files intact, diff inside the allowlist, ledger consistent")
        return 0
    print("guard violations:")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_diff(args) -> int:
    diff = _harness(args).pending_diff()
    print(diff if diff.strip() else "(no pending edits)")
    return 0


def cmd_report(args) -> int:
    from arh.report import write_report

    harness = _harness(args)
    png, md = write_report(harness, args.out)
    print(f"wrote {md}\nwrote {png}")
    return 0


def cmd_loop(args) -> int:
    from arh.agent import TOOL_SCHEMAS, briefing, run_loop, system_prompt
    from arh.models import ChatModel, ScriptedModel

    harness = _harness(args)
    if args.dry_run:
        print("=== system prompt ===")
        print(system_prompt(harness))
        print("\n=== first user message ===")
        print(briefing(harness))
        print("\n=== tools ===")
        print(", ".join(t["function"]["name"] for t in TOOL_SCHEMAS))
        return 0
    if args.agent == "scripted":
        if not args.script:
            raise HarnessError("--agent scripted needs --script <experiments.json>")
        model = ScriptedModel.from_experiment_script(args.script)
    else:
        provider = None if args.agent == "llm" else args.agent
        try:
            model = ChatModel(model=args.model, provider=provider, max_requests=args.max_requests)
        except (RuntimeError, ImportError) as exc:  # missing key or missing openai package
            raise HarnessError(f"{exc}; or run offline with --dry-run / --agent scripted") from exc
    print(f"[arh] proposer: {model.name}; up to {args.max} experiments")
    result = run_loop(
        harness,
        model,
        max_experiments=args.max,
        max_seconds=args.minutes * 60 if args.minutes else None,
    )
    summary = f"{len(result.experiments)} experiments, {result.kept} kept"
    print(f"\n[arh] stopped: {result.stopped_because}. " + ". ".join(filter(None, [summary, _usage(result)])))
    return 0


def _usage(result) -> str:
    """Three different facts, kept apart: what we spent in requests, in tokens,
    and in money. A price of 0.0 that the provider actually reported (a free
    model) is not the same as a provider that reports no price at all."""
    if not result.requests and not result.tokens:
        return ""
    cost = f"${result.cost:.4f}" if result.cost is not None else "n/a (provider reports no price)"
    return f"{result.requests} requests, {result.tokens} tokens, cost {cost}"


def _harness(args) -> Harness:
    return Harness(find_task_dir(Path(args.task) if args.task else None))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
