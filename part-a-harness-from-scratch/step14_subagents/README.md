# Step 14: subagents

**Goal:** do expensive searching without spending the main conversation's context
on it.

**The idea:** the `task` tool starts a second `Agent` with an empty transcript, a
read-only policy and a smaller toolset. It runs its own loop to completion and
only its final answer comes back as the tool result. Thirty tool calls happen;
one sentence is kept.

**Compaction vs subagents**: compaction is damage control after the context is
already full. A subagent stops it filling in the first place. Reach for a
subagent *before* the exploration, and for compaction after a long session.

## The code

`nanoharness/subagent.py`:

```python
SUBAGENT_TOOLS = ("bash", "read_file", "list_dir", "load_skill")
```

Why: the toolset is the safety mechanism. No `task` means no recursion (a
subagent cannot start subagents); no `write_file` / `edit_file` / `write_todos`
means it cannot change the project or the parent's plan.

```python
"Investigate with your tools, then reply with the findings themselves: exact paths, "
"line numbers, commands and error text. Your reply is the only thing that reaches the "
"main conversation, so never answer with 'I looked at it' - say what you found."
```

Why: the child's context is deleted the moment it returns. If the answer says
"I read the files", everything it learned is gone.

```python
prompt: Complete instructions for the subagent. It sees none of this conversation,
    so repeat every fact it needs, and say exactly what to report back.
```

Why: the parent model has to be told that the child is blind to the conversation,
or it writes prompts like "check the other one too".

`nanoharness/agent.py`:

```python
def spawn_child(self, tools: list[str], note: str) -> "Agent":
    """A fresh agent: empty transcript, restricted tools, a policy that never asks."""
    return Agent(
        root=self.root,
        ui=self.ui.child(),
        session=None,  # a subagent's transcript is thrown away, so nothing to log
        policy=self.policy.read_only(),
        approve=self.approve,
        sandbox=self.sandbox,
        tools=tools,
        note=note,
    )
```

Why: same project, same sandbox, same console - but a fresh transcript, no
session log (there is nothing to resume) and a policy that denies instead of
asking, so a subagent never interrupts the user.

```python
if self.tools is not None and name not in self.tools:
    # The schema never offered it, but a model can still invent a name.
    return f"Error: the tool {name!r} is not available here. You may use: {', '.join(self.tools)}."
```

Why: the restricted schema is a suggestion; this line is the rule.

`nanoharness/ui.py`:

```python
def child(self) -> "UI":
    """Same console, deeper indent: a subagent's work is visibly nested."""
    return UI(console=self.console, indent=self.indent + 3)
```

Why: one console, two indent levels. Without it the user cannot tell which agent
is talking.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> use a subagent to find every place the permission policy is consulted, then summarise it for me
python -m pytest -q test_step.py
```

## What you should see

```text
╭─ task ───────────────────────────────────────────────╮
│ {"description": "find policy call sites", ...}       │
╰──────────────────────────────────────────────────────╯
> subagent: find policy call sites
   ╭─ bash ─────────────────────────────────────────────╮
   │ $ grep -rn "policy.check" nanoharness              │
   ╰────────────────────────────────────────────────────╯
   nanoharness/agent.py:152: verdict = self.policy.check(...)
< subagent finished: find policy call sites (6 messages, then discarded)
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/subagent.py` | new: `SUBAGENT_TOOLS`, `SUBAGENT_NOTE`, the `task` tool |
| `nanoharness/agent.py` | `tools` and `note` parameters, `spawn_child`, refuses tools outside its own set |
| `nanoharness/ui.py` | `indent`, `child()`, `emit()`, subagent start/finish lines |
| `nanoharness/permissions.py` | `task` classified as safe (its inner calls are gated on their own) |
| `nanoharness/cli.py` | banner text |
| `test_step.py` | rewritten: isolation, toolset limits, read-only policy, indentation |
| `README.md` | this file |

## Gotchas

- Subagents run one at a time. Running them in parallel needs threads and an
  output model that can interleave - a good exercise, not a one-idea step.
- A subagent costs a full prompt of its own (system prompt, skills, environment).
  Below about ten tool calls of work, it is cheaper to do it inline.
- The child shares the parent's `approve` callback but a read-only policy, so it
  should never reach it. The test asserts that.
