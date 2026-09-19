# Step 03: the first tool

**Goal:** let the model act on the machine - once, under our control.

**The idea:** a tool is a JSON schema (for the model) plus a Python function (for
us). The model can only *propose* a call; the harness decides whether to run it
and what to report back. This step deliberately stops after one round: we run the
command, drop the output into the transcript, and give you the prompt back. That
missing "send the result back to the model" is exactly what step 05 adds.

## The code

`nanoharness/tools.py`:

```python
BASH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a shell command in the current working directory and return its "
            "combined stdout and stderr plus the exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": 'The command to run, e.g. "ls -la" or "git status".',
                }
            },
            "required": ["command"],
        },
    },
}
```

Why: the description and the parameter descriptions are prompt text. A vague
description produces vague tool calls, so write them like documentation.

```python
process = subprocess.Popen(
    ["bash", "-c", command],
    stdin=subprocess.DEVNULL,  # a command that waits for input would hang the agent forever
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,  # the model wants the error text as much as the output
    start_new_session=True,  # own process group, so a timeout can kill the children too
```

Why: three decisions that keep a harness alive. No stdin (`git commit` without
`-m` would block forever), merged stderr (errors are the most useful output a
model gets), and a fresh process group so `_kill_group` can remove background
children on timeout.

```python
return f"{output}\n[exit code {process.returncode}]"
```

Why: the exit code is how the model knows whether the command worked. Text only -
the model has no other channel.

`nanoharness/cli.py`:

```python
for call in reply.get("tool_calls") or []:
    arguments = json.loads(call["function"]["arguments"] or "{}")
    command = arguments["command"]
    output = tools.run_bash(command)
    transcript.append({"role": "tool", "tool_call_id": call["id"], "content": output})
```

Why: `arguments` arrives as a **JSON string**, not a dict. And the result must be
a `role="tool"` message carrying the same `tool_call_id`, or the next request is
rejected by the API.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> how many python files are in this directory?
you> what did that output mean?     # now the model sees the tool result
python -m pytest -q test_step.py
```

## What you should see

```text
you> how many python files are in this directory?

[bash] $ find . -name "*.py" | wc -l
       5
[exit code 0]
[the model has not seen this yet - ask it a follow-up question]
[4 messages in memory | in=180 out=22 cost=$0.000031]
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/tools.py` | new: the bash schema and the subprocess runner |
| `nanoharness/cli.py` | sends `tools=[BASH_SCHEMA]`, executes tool calls, appends `role=tool` results |
| `test_step.py` | rewritten: process-group timeout, stdin, call-id pairing, single-shot behaviour |
| `README.md` | this file |

## Gotchas

- `json.loads` on the arguments can fail: models do emit broken JSON. Here it
  would crash the REPL; step 04 turns every such failure into a message the model
  can read and correct.
- `text=True` with `errors="replace"` keeps binary output from raising
  `UnicodeDecodeError` in the middle of a turn.
- The timeout kills the process group, not just the shell, so
  `sleep 30 & sleep 30` cannot outlive the call.
