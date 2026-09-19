---
name: autoresearch
description: The experiment protocol for an arh autoresearch loop - read the ledger, form one hypothesis, change one editable file, measure it with `arh run`, read the verdict, repeat. Use whenever working inside a directory that contains autoresearch.toml, or when the user asks to improve a metric by running experiments.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task
---

# Autoresearch loop protocol

You are the proposer in a measured research loop. The harness (`arh`) owns the
scoring, the git history and the verdict. You own exactly one thing: the next
idea. Play that role and nothing else.

## Before you start

```bash
arh status          # branch, baseline, best, recent experiments, pending edits
```

If it reports that the task is not initialised: `arh init <task_dir>` then
`arh baseline`. If `arh` is not on PATH, install it:
`pip install -e <repo>/part-c-autoresearch-harness`.

Read the task's `program.md` (the research direction) and `autoresearch.toml`
(the rules) once, at the start. Read the frozen evaluator once so you know what
is actually being measured; never edit it.

## The loop

Repeat until the experiment budget is spent or the user stops you.

1. **Read the ledger before thinking.** `arh status`, or the tail of
   `.arh/results.tsv`. Never repeat an idea that already failed; never undo a
   kept improvement without a reason you can write down.
2. **Form one hypothesis.** One sentence: what you will change, and what you
   expect the metric to do. Write it into the `-m` description -- the ledger is
   the only memory that survives a compacted context.
3. **Make ONE focused change** to an editable file. Two changes in one
   experiment teach you nothing about either. If a hook blocks your edit, the
   file is frozen: do not work around it, pick a different idea.
4. **Audit risky diffs.** Before running, if the change touches data loading,
   the loss, the evaluation call, masking/attention, or anything that could see
   held-out data, dispatch the `experiment-reviewer` subagent on `arh diff`
   first. It is cheap compared to a false discovery.
5. **Measure it.**
   ```bash
   arh run -m "one hidden layer with 32 tanh units; expect val_loss well under the linear model"
   ```
   The harness runs the command under its time budget, checks the guards, and
   then either commits your change or reverts it.
6. **Read the verdict, then act on it.**
   - `KEEP` -- committed; it is the new baseline. Build on it.
   - `DISCARD` -- measured and worse; your edit is already gone from disk.
     Record what you learned in the next description.
   - `CRASH` -- it did not finish. Read the tail of `.arh/runs/<id>.log`. Fix a
     trivial slip (typo, missing import) once; otherwise drop the idea.
   - `INVALID` -- a guard fired: a frozen file changed, the diff added a
     forbidden pattern, the score was outside plausible bounds, or the holdout
     did not confirm. Treat this as a bug in your idea, never as an obstacle to
     route around.
7. **Go back to 1.** Do not ask the user whether to continue. Continue.

## Judgement

- **Simplicity is a criterion, not a nicety.** Weigh every gain against the
  code it costs. A 0.001 gain for thirty lines of special cases is not worth
  keeping; the same gain from deleting code always is.
- **One variable at a time**, so the ledger stays interpretable.
- **Noise is real.** If a "win" is within the task's `min_delta`, it is not a
  win. Prefer ideas with a mechanism you can explain.
- **A crash is data.** Log it, move on.
- **Never optimise the measurement.** If you catch yourself wanting to change
  the evaluator, the split, the time budget or the METRIC line, stop and tell
  the user what the current measurement cannot see. That conversation is the
  useful outcome; a quietly edited ruler is a ruined experiment.

## Reporting

After a batch of experiments (or when the user asks):

```bash
arh report     # writes .arh/progress.png and .arh/report.md
```

Summarise in plain language: what was kept, what the metric did, which ideas
failed and what that rules out, and what you would try next.
