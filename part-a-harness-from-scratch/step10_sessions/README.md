# Step 10: sessions, rewind, and commands the model never sees

**Goal:** survive closing the terminal, and give the user controls that are not
prompts.

**The idea:** every message that enters the transcript is appended to a JSONL
file under `.nanoharness/sessions/`. Append-only means a crash can lose at most
the last line. Operations that *remove* messages (`/rewind`) are recorded as
their own event and replayed, never by rewriting the file. And anything typed
starting with `/` is handled by the harness - slash commands are a different
channel from the conversation.

## The code

`nanoharness/agent.py`:

```python
def add(self, message: dict) -> None:
    """The only way a message enters the transcript, so the log cannot drift."""
    self.messages.append(message)
    if self.session:
        self.session.record("message", message=message)
```

Why: one choke point. If appending and logging live in two places they diverge
on the day you are debugging something else.

`nanoharness/session.py`:

```python
elif kind == "rewind":
    del messages[int(event.get("keep", len(messages))) :]
```

Why: replay is a fold over events. The file is never edited, and `/rewind`
followed by `--resume` gives back exactly the transcript the user was looking at.

```python
except json.JSONDecodeError:
    continue  # a half-written last line after a kill -9
```

Why: the only line that can be corrupt is the last one, and skipping it is
better than refusing to open the session.

```python
for call in message["tool_calls"]:
    if call["id"] not in answered:
        fixed.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": "Error: this tool call was interrupted and never ran. Try it again if you still need it.",
            }
        )
```

Why: this is the repair that makes resume reliable. A log that ends with unanswered
tool calls is rejected by every provider; we answer them with an error the model
understands, and `repair` is idempotent.

`nanoharness/commands.py`:

```python
if not line.startswith("/"):
    return False
...
if entry is None:
    ui.error(f"unknown command {name}. Try /help.")
    return True
```

Why: an unknown `/comapct` is a typo, not a question. Sending it to the model
would waste a call and confuse the transcript.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> summarise what nanoharness/session.py does
you> /rewind
you> /sessions
you> /exit
python -m nanoharness --resume        # same conversation, new process
python -m nanoharness --session 202609
python -m pytest -q test_step.py
```

## What you should see

```text
nanoharness step10 | openrouter | deepseek/deepseek-v4-flash-0731:free
session: 20260919-142530-a1b2 (new)
commands: /help, /exit, /clear, /sessions, /resume, /rewind
...
you> /sessions
  20260919-142530-a1b2  2026-09-19 14:27    4 msgs  summarise what nanoharness/se (current)
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/session.py` | new: `Session` (record/events/replay/summary), listing helpers, `repair` |
| `nanoharness/commands.py` | new: `@command` registry, `/help /exit /clear /sessions /resume /rewind` |
| `nanoharness/agent.py` | takes a session, routes all appends through `add()`, gains `load()` |
| `nanoharness/cli.py` | `--resume` / `--session` flags, command dispatch before the model |
| `test_step.py` | rewritten: logging, replay, rewind events, repair, command isolation |
| `README.md` | this file |

## Gotchas

- Session files are per project directory: run the harness somewhere else and
  `--resume` finds nothing. That is deliberate.
- The todo list is not restored on resume. It is derivable from the transcript,
  and leaving it out keeps `replay()` honest about what it rebuilds.
- `.nanoharness/` is in the repository's `.gitignore`; session logs contain your
  prompts and tool output.
