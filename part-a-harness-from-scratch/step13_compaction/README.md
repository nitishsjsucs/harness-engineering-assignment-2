# Step 13: compaction

**Goal:** let a session run all afternoon without hitting the context window or
paying for the same file content twenty times.

**The idea:** two mechanisms, cheapest first.

1. **Trim**: after a turn ends, its tool results have done their job. Results
   longer than 400 characters from older turns become a one-line stub.
2. **Compact**: when the estimated size crosses 75% of the context window,
   everything before the current turn is summarised by a tool-less model call,
   and the summary is folded into the system prompt.

Both rewrite history and therefore cost a cache miss, which is why both happen as
rarely as possible. The cut is always at a user message, so a tool call is never
separated from its result.

## The code

`nanoharness/compaction.py`:

```python
def estimate_tokens(messages: list[dict]) -> int:
    """Four characters per token is wrong in detail and right enough to budget with."""
    return len(json.dumps(messages, ensure_ascii=False, default=str)) // 4
```

Why: a real tokeniser would need the model's vocabulary and a network call. We
need a number to compare with a threshold, and this one is free.

```python
messages[index] = {
    **message,
    "content": f"[{len(content)} characters of tool output from an earlier turn, "
    "trimmed by the harness. Run the tool again if you need it.]",
}
```

Why: the stub says what was there and how to get it back, so the model can decide
to re-read instead of hallucinating the content.

```python
starts = [index for index, message in enumerate(messages) if message.get("role") == "user"]
if len(starts) <= nth_from_end:
    return None
return starts[len(starts) - nth_from_end]
```

Why: user messages are the only safe cut points. Cutting anywhere else can strand
a `role="tool"` message whose call is gone, which every provider rejects.

```python
reply, _usage = llm.chat(
    [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "\n".join(parts)}]
)
```

Why: no `tools=` argument, so the summariser cannot start doing work of its own.
Its input is flattened text (`transcript_text`), which is easy to truncate and
impossible to malform.

```python
if previous:
    parts.append(f"Summary of even older messages:\n{previous}\n")
```

Why: compaction is recursive. The second compaction summarises the first summary
plus what came after it.

`nanoharness/agent.py`:

```python
def system_text(self) -> str:
    if not self.summary:
        return self.system
    return f"{self.system}\n\n# Summary of the earlier part of this conversation\n{self.summary}"
```

Why: the summary goes where stable context goes. It replaces the messages it was
made from, so the prefix is stable again immediately after the compaction.

`nanoharness/session.py`:

```python
elif kind == "compact":
    summary = event.get("summary")
    del messages[: int(event.get("cut", 0))]
```

Why: a resumed session must land in the same state, summary and all - not replay
a transcript that was already summarised away.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> read every python file in this project one at a time
you> /compact
you> what were we doing?
HARNESS_CONTEXT_WINDOW=8000 python -m nanoharness    # make automatic compaction easy to trigger
python -m pytest -q test_step.py
```

## What you should see

```text
you> /compact
about 18422 -> 2571 estimated tokens
1. Goal - the user asked for a tour of nanoharness ...
```

and during a long turn, automatically:

```text
[compacted 34 messages into a summary; 6 left]
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/compaction.py` | new: `estimate_tokens`, `trim_old_tool_results`, `turn_start`, `compact`, `summarise`, `transcript_text` |
| `nanoharness/agent.py` | `self.summary`, `system_text()`, trims at turn start, compacts inside the loop |
| `nanoharness/session.py` | replay returns `Restored(messages, summary)` and applies `compact` events |
| `nanoharness/commands.py` | `/compact`, and `/resume` restores the summary |
| `nanoharness/cli.py` | resume restores the summary |
| `test_step.py` | rewritten: trimming, cut rule, folding, auto-trigger, resume, `/compact` |
| `README.md` | this file |

## Gotchas

- `HARNESS_CONTEXT_WINDOW` defaults to 128000 and is a *budget*, not the model's
  real limit. Set it lower than the model's window: the estimate is rough.
- Compaction cannot help inside one enormous turn - there is no earlier user
  message to cut at. Trimming and `MAX_STEPS` are what bound that case.
- Compaction is lossy by design. Everything the next turn needs must survive in
  the summary, which is why `SUMMARY_SYSTEM` insists on exact paths, commands and
  error strings.
