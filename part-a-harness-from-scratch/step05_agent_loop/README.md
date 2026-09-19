# Step 05: the agent loop

**Goal:** stop asking the user for the follow-up. The harness feeds tool results
back to the model until the model is done.

**The idea:** an agent is a `while` loop with a bound. Call the model; if it
returned tool calls, run them, append one `role="tool"` message per call, and
call again; if it returned text, that is the answer. `MAX_STEPS` keeps a confused
model from looping forever.

## The code

`nanoharness/agent.py`:

```python
for _ in range(MAX_STEPS):
    reply, usage = llm.chat(self.request(), tools=registry.schemas())
    self.messages.append(reply)
    calls = reply.get("tool_calls") or []
    if not calls:
        return reply.get("content") or ""
    self.run_tools(calls)
```

Why: the loop is this small. Everything in steps 06-15 is context, safety and
ergonomics around these six lines.

```python
def request(self) -> list[dict]:
    """What we send. The system prompt is rebuilt every time, never stored."""
    return [{"role": "system", "content": SYSTEM}, *self.messages]
```

Why: the transcript holds only user/assistant/tool messages. Keeping the system
prompt outside it means we can change it later (step 07 appends project
instructions, step 13 folds in a summary) without rewriting history.

```python
def tool_message(call: dict, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call["id"], "content": content}
```

Why: the `tool_call_id` is the contract. Every id in `tool_calls` must be
answered by exactly one `role="tool"` message, in the same assistant turn, or the
next request is a 400.

```python
except KeyboardInterrupt:
    for pending in calls[index:]:
        self.messages.append(tool_message(pending, "Error: interrupted by the user."))
    raise
```

Why: Ctrl-C in the middle of a long `pytest` run must not corrupt the transcript.
We answer the remaining calls with an error and then let the interrupt through.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> how many lines of Python are in this step, and which file is the longest?
python -m pytest -q test_step.py
```

## What you should see

Several tool calls inside one turn, then a single answer:

```text
you> how many lines of python are in this step?

[in=412 out=18 cost=$0.000061]

[bash] {"command": "find . -name '*.py' | xargs wc -l"}
      41 ./nanoharness/llm.py
     ...
[in=690 out=64 cost=$0.000104]

About 300 lines across five files; nanoharness/registry.py is the longest at 110.
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/agent.py` | new: `Agent`, the bounded loop, `tool_message`, interrupt safety |
| `nanoharness/cli.py` | shrinks to a REPL that calls `Agent.run` and prints the answer |
| `test_step.py` | rewritten: tool/result ordering, id pairing, error recovery, MAX_STEPS |
| `README.md` | this file |

## Gotchas

- Tool results must be appended in the order the calls arrived. Models that emit
  parallel calls expect all of them answered before the next assistant message.
- The loop returns `""` if a model answers with an empty message. The REPL prints
  it as a blank line rather than crashing.
- `MAX_STEPS` is per user turn, not per session.
