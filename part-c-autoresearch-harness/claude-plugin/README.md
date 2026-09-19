# `claude-plugin/` -- the `autoresearch` plugin for Claude Code

This is the "plugin for your favourite coding assistant" half of Part C. The
engine (`arh`) does the measuring; this makes Claude Code a well-behaved
proposer in front of it.

```
claude-plugin/
  .claude-plugin/plugin.json     the manifest (name, version, author)
  commands/start.md              /autoresearch:start <task-dir> [tag]
  commands/status.md             /autoresearch:status [task-dir]
  commands/report.md             /autoresearch:report [task-dir]
  skills/autoresearch/SKILL.md   the loop protocol Claude follows
  agents/experiment-reviewer.md  a subagent that audits a diff before it runs
  hooks/hooks.json               PreToolUse + PostToolUse wiring
  hooks/guard_frozen.py          BLOCKS edits to frozen files and to the ledger
  hooks/remind_run.py            reminds the assistant to measure the edit
  hooks/task_lookup.py           shared, stdlib-only helpers for both hooks
```

## Install

From the repo root, with the engine already installed
(`pip install -e part-c-autoresearch-harness`):

```
/plugin marketplace add nitishsjsucs/harness-engineering-assignment-2
/plugin install autoresearch@nitishsjsucs-harness
```

Local development, no marketplace:

```bash
claude --plugin-dir part-c-autoresearch-harness/claude-plugin
claude plugin validate part-c-autoresearch-harness/claude-plugin   # manifest check
```

## Then

```
/autoresearch:start part-c-autoresearch-harness/tasks/quickstart
/autoresearch:status
/autoresearch:report
```

`/autoresearch:start` runs `arh init` and `arh baseline`, then hands over to
the skill, which is the loop protocol: read the ledger, one hypothesis, one
edit, `arh run -m "..."`, read the verdict, repeat, never edit the frozen half.

## The interesting part: the hook

Commands and skills are instructions; Claude can talk itself out of them. The
`PreToolUse` hook cannot be talked out of anything, because it runs before the
tool call and returns a decision:

```python
if matches(rel, state.get("editable")):
    allow()

why = "a frozen evaluation file" if matches(rel, state.get("frozen")) else "not on the editable list"
deny("autoresearch: {0} is {1} for task '{2}'. Only {3} may change during an experiment. ...")
```

What it blocks, inside any directory that contains an initialised task
(`autoresearch.toml` plus `.arh/state.json`):

- frozen files (`prepare.py`: the data prep and the evaluator),
- `autoresearch.toml` itself (the rules of the task),
- anything under `.arh/` (the ledger and the state -- append-only evidence),
- any other file that is not on the editable list.

It **allows** everything else, silently, including every file outside a task.
Failures fail closed: an unparseable payload, a missing file path, or an
unreadable `state.json` all deny with an explanation.

It reads `.arh/state.json` (written by `arh init`) rather than the TOML spec,
so it needs nothing but the Python standard library -- it works with the system
`python3` even when `arh` is installed in a virtualenv. `tests/test_hooks.py`
drives both hooks exactly the way Claude Code does (JSON on stdin) and asserts
that the hook's copy of the path-matching rules agrees with the engine's.

The `PostToolUse` hook adds one line of context after an editable file changes:
measure this one change before starting the next. Unmeasured stacked edits are
the most common way an autoresearch session turns into a mystery.

Defence in depth, on purpose: the hook is convenience, the engine is truth. No
hook matcher can see every shell redirect, so `arh run` hashes the frozen files
before *and* after each run regardless.

## The reviewer subagent

`agents/experiment-reviewer.md` is an independent auditor. Claude dispatches it
before running a risky diff (anything touching data loading, the loss,
evaluation, masking, randomness or timing). It reads `arh diff`, `arh status`,
`arh guard`, the spec and the evaluator, and answers `APPROVE`,
`APPROVE WITH NOTE` or `BLOCK` with file:line findings. It exists because an
implementer -- human or model -- overtrusts its own change.
