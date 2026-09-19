# `arh/` -- the engine

Ten small files. Each one owns a single question, which is what makes the
whole thing reviewable on camera.

| file | the question it answers | lines worth reading |
|---|---|---|
| `spec.py` | what is a task? | `TaskSpec`, `matches()`, `is_better()` |
| `runner.py` | how do I run one thing safely? | `run_command()`, `parse_output()` |
| `ledger.py` | what happened, in order? | `Ledger.append()` |
| `gitops.py` | how do I undo? | `Git.commit_paths()`, `Git.restore()` |
| `guards.py` | is this number trustworthy? | `check_hashes()`, `scan_diff()` |
| `engine.py` | keep it or revert it? | `Harness._evaluate()` |
| `report.py` | what did we learn? | `plot_progress()` |
| `models.py` | who proposes? | `ChatModel` (openrouter/openai/gemini), `ScriptedModel` |
| `agent.py` | how does a model drive the loop? | `TaskTools`, `run_loop()` |
| `cli.py` | how does a human (or Claude Code) drive it? | `build_parser()` |

## The one function to read first

`engine.Harness._evaluate()` is the whole product in about sixty lines:

```python
# 1. pre-run guards: cheap, so they run before any compute is spent
problems = (
    guards.check_allowlist(rec["files"], spec)
    + self._hash_problems()
    + guards.scan_diff(diff_text, spec.forbid_patterns)
)
if problems:
    return self._finish(rec, "invalid", "; ".join(problems))
```

Then the run, then the same hash and allowlist checks **again** (training code
can rewrite files while it runs), then `_judge()`, then either a commit or a
restore, and always a ledger row.

## Design decisions that are easy to miss

**The ledger is the memory, not the context window.** `agent.run_loop()` starts
a fresh conversation for every experiment, built from `briefing()`, which reads
the ledger and the current editable files. A loop can run for hours without the
context growing, and a crashed process loses nothing.

**`None` in the run environment means "unset".** `Harness._run_env()` passes
`ARH_EVAL_SPLIT=None` for ordinary runs, so a holdout switch left in someone's
shell cannot leak into a normal experiment.

**A quota is part of the budget.** `ChatModel` counts its own requests and
`arh loop --max-requests N` raises `BudgetExceeded`, which the loop treats as a
clean stop (ledger intact, usage reported) rather than an error. Rate-limit,
auth and payment errors are never retried -- on a free tier, a retry loop is
just a faster way to spend the day's quota.

**Three kinds of spend, reported separately.** `usage` returns requests, tokens
and cost, and cost is `None` when the provider reports no price at all (OpenAI)
but `0.0` when it reports free (an OpenRouter `:free` model). The CLI prints
`cost n/a` for the first and `$0.0000` for the second, because they are
different facts.

**Statuses mean different things.**

| status | meaning | who is at fault |
|---|---|---|
| `keep` | measured, better, committed | -- |
| `discard` | measured, not better | the idea |
| `crash` | never produced a score (timeout, exit code, NaN) | the idea |
| `invalid` | produced a score nobody should trust | the *setup* of the experiment |

**State is derived; the ledger is the truth.** `.arh/state.json` is a cache of
"where are we" (branch, best commit, frozen hashes). If it were lost, the
ledger and git history would still describe the run.

**One experiment at a time.** `Harness._lock()` is an `O_EXCL` lock file
holding a pid, so two terminals (or two agents) cannot interleave runs on the
same task. A stale lock from a killed process is detected and removed.

## Extending it

- a new task: write `autoresearch.toml`, a frozen `prepare.py` that owns the
  metric, and an editable `train.py`. Nothing in `arh/` needs to change.
- a new proposer: anything with a `complete(messages, tools) -> Reply` method
  can be passed to `run_loop` (see `models.ScriptedModel`).
- a new guard: a pure function in `guards.py` plus one line in
  `engine._evaluate()`; add a spec field if it needs configuring.
