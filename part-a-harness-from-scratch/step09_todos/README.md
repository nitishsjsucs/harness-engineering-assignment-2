# Step 09: todos, or a plan the model cannot forget

**Goal:** keep multi-step work on track, and show the user what the agent thinks
it is doing.

**The idea:** `write_todos` replaces the whole list at once (no patch language to
get wrong), the harness validates it, and the plan lives in `agent.todos` - not
in the transcript. It is re-injected with the environment block, so the current
plan is always the last thing the model reads before choosing its next action.
Planning in the chat scrolls away; planning in harness state does not.

Making this work needs one small mechanism: a tool that can reach harness state.

## The code

`nanoharness/registry.py`:

```python
INJECTED = "agent"
...
if name == INJECTED:
    continue  # harness state: the model must not see it or set it
...
arguments.pop(INJECTED, None)  # a model that guesses the name still cannot set it
if INJECTED in inspect.signature(entry["fn"]).parameters:
    arguments[INJECTED] = agent
```

Why: a tool that declares a parameter called `agent` gets the live `Agent`
instance, and that parameter is stripped from the schema. Step 14 reuses this to
let `task` spawn subagents.

`nanoharness/todos.py`:

```python
class Todo(TypedDict):
    content: str
    status: Status
```

Why: the `TypedDict` plus `Literal` statuses give the model an exact schema -
array of objects, `status` an enum - straight from the type hints of step 04.

```python
if in_progress > 1:
    return f"{in_progress} items are in_progress; exactly one item may be in progress at a time."
```

Why: the constraint is what makes the list useful. Errors are returned as text,
so a model that breaks the rule is told how to fix it and the old plan stays.

`nanoharness/prompt.py`:

```python
if todos:
    lines.append("current plan (keep it up to date with write_todos):")
    lines.append(todo_render(todos))
```

Why: late injection again. One current copy near the end of the request beats six
historical copies scattered through the transcript.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> plan and then do this: list the python files here, count their lines, and write the counts to scratch/sizes.md
python -m pytest -q test_step.py
```

## What you should see

```text
╭─ write_todos ───────────────────────────────────╮
│ {"todos": [{"content": "list the python fil...  │
╰─────────────────────────────────────────────────╯
  [x] list the python files
  [~] count the lines
  [ ] write scratch/sizes.md
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/todos.py` | new: `Todo`, the `write_todos` tool, `validate`, `render` |
| `nanoharness/registry.py` | hides and injects the `agent` parameter |
| `nanoharness/prompt.py` | environment block renders the current plan |
| `nanoharness/agent.py` | owns `self.todos`, passes `agent=self` to `run_tool`, draws the checklist |
| `nanoharness/ui.py` | `todos()` renderer |
| `nanoharness/cli.py` | banner text |
| `test_step.py` | rewritten: schema shape, validation, injection, late plan injection |
| `README.md` | this file |

## Gotchas

- Replace-the-whole-list is deliberate. "Update item 3" needs stable ids and a
  patch format, and models get both wrong.
- The plan is not written to disk yet, so it dies with the process. Step 10 adds
  sessions; restoring the plan on resume is left as an exercise.
- A rejected plan does not clear the old one: validation runs before assignment.
