---
description: Set up an arh autoresearch task (init + baseline) and enter the experiment loop.
argument-hint: <task-dir> [tag]
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task
---

# Start an autoresearch loop on `$1`

Current state of that directory:

!`ls -la "$1" 2>&1 | head -20`

!`arh status -C "$1" 2>&1 | head -30`

## What to do

1. If `arh` is missing (`command -v arh` is empty), tell the user to install it
   and stop:
   `pip install -e <repo>/part-c-autoresearch-harness` (add `[torch]` for the
   tinygpt task).
2. If the status above says the task is not initialised, run:
   ```bash
   arh init "$1" ${2:+--tag "$2"}
   arh baseline -C "$1"
   ```
   `arh init` defaults to an isolated git repository under `<task>/.arh/git`,
   so it will not create branches in the surrounding repository. Report the
   baseline number to the user before going further.
3. Read `$1/program.md` and `$1/autoresearch.toml`, then read the frozen
   evaluator once so you know exactly what is being scored.
4. Follow the `autoresearch` skill's protocol: one hypothesis, one edit to an
   editable file, `arh run -C "$1" -m "..."`, read the verdict, repeat. Keep
   going without asking for permission between experiments.
5. Stop when the user stops you or `max_experiments` is reached, then run
   `arh report -C "$1"` and summarise what was learned.

If anything in `$ARGUMENTS` is unclear (for example no task directory was
given), ask once, then proceed.
