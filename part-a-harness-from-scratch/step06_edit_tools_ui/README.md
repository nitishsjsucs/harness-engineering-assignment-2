# Step 06: editing files, and a UI worth watching

**Goal:** let the agent change code, and make the terminal readable while it does.

**The idea:** two write tools with strict contracts (`write_file` replaces a whole
file, `edit_file` replaces one exact snippet and refuses ambiguous matches), plus
a `ui.py` that owns all rendering. The UI imports no model code, so the loop can
be run head-less in tests and reused by subagents in step 14.

## The code

`nanoharness/tools.py`:

```python
found = text.count(old_text)
if found == 0:
    return (
        f"Error: old_text was not found in {path}. Read the file again and copy the exact "
        "text, including whitespace."
    )
if found > 1 and not replace_all:
    return (
        f"Error: old_text appears {found} times in {path}. Include more surrounding lines to "
        "make it unique, or set replace_all to true."
    )
```

Why: a "replace the first match" edit tool silently corrupts files. Refusing 0 or
more than 1 match turns an ambiguous edit into a message the model can fix by
quoting more context. `replace_all` makes the bulk case explicit instead.

```python
target.parent.mkdir(parents=True, exist_ok=True)
```

Why: models write `tests/test_thing.py` before the `tests/` directory exists.

`nanoharness/ui.py`:

```python
@contextmanager
def thinking(self, label: str = "thinking"):
    status = self.console.status(f"[dim]{label}...", spinner="dots")
```

Why: the only moment the user cannot tell "working" from "hung" is the model
call, so that is the only place with a spinner.

```python
def tool_result(self, text: str, lines: int = RESULT_LINES) -> None:
    rows = text.splitlines()
    shown = rows[:lines]
```

Why: the screen gets 8 lines; the model gets the whole result. Truncating the
*model's* copy is a different decision, and it belongs in step 13.

```python
if name == "bash":
    return f"$ {arguments.get('command', '')}"
```

Why: `describe()` renders a tool call the way a human reads it. Raw JSON
arguments on screen are noise.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> create scratch/calc.py with an add() function that is deliberately wrong, then fix it with edit_file
python -m pytest -q test_step.py
```

## What you should see

```text
╭─ write_file ─────────────────────────────────────────╮
│ scratch/calc.py (4 lines)                            │
╰──────────────────────────────────────────────────────╯
Created scratch/calc.py (4 lines)
╭─ edit_file ──────────────────────────────────────────╮
│ scratch/calc.py: replace 'return a - b' ...          │
╰──────────────────────────────────────────────────────╯
Edited scratch/calc.py: replaced 1 occurrence(s)
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/ui.py` | new: `UI` (spinner, panels, usage line, markdown answers, prompt input), `describe` |
| `nanoharness/tools.py` | adds `write_file` and `edit_file` |
| `nanoharness/agent.py` | takes a `UI` and reports through it instead of `print` |
| `nanoharness/cli.py` | creates the `UI`, reads input through it |
| `test_step.py` | rewritten: edit contracts, UI rendering, "ui.py imports no model code" |
| `README.md` | this file |

## Gotchas

- `read_file` returns line numbers; `edit_file` needs the text *without* them.
  The docstring says so, because that is the only place the model reads.
- `UI.ask` falls back to `input()` when stdin is not a terminal, so piping
  `/exit` into the REPL works in scripts and CI.
- Nothing stops the agent writing outside the project yet. That is step 11
  (permissions) and step 12 (sandbox).
