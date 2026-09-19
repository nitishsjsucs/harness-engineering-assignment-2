# Step 07: context injection, early and late

**Goal:** give the model project rules and fresh facts without destroying prompt
caching.

**The idea:** split context by how often it changes.

- **Early / stable**: base instructions plus `AGENTS.md`, built once at startup
  and sent as message 0 on every call, byte for byte identical. Providers cache
  long identical prefixes and bill them at a discount, and OpenRouter reports the
  hit as `usage.prompt_tokens_details.cached_tokens`.
- **Late / volatile**: cwd, git branch, git status, the clock. These are appended
  to the *request* as the final message and never stored in the transcript. A
  timestamp inside the transcript would rewrite history on every turn and destroy
  the cache for the whole conversation.

## The code

`nanoharness/prompt.py`:

```python
def system_prompt(root: Path) -> str:
    parts = [BASE]
    instructions = Path(root) / INSTRUCTION_FILE
    if instructions.is_file():
        parts.append(f"# Project instructions from {INSTRUCTION_FILE}\n{body}")
```

Why: `AGENTS.md` is how a repository tells any agent its house rules. Reading it
once at startup keeps the prefix stable even if the file changes mid-session.

```python
lines = [
    "This block is attached by the harness before every request. It is not part of the "
    "conversation and the user did not type it.",
    f"cwd: {root}",
    f"now: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
]
```

Why: without that first line, models answer the environment block as if the user
had asked about the weather in their git repo.

`nanoharness/agent.py`:

```python
return [
    {"role": "system", "content": self.system},
    *self.messages,
    {"role": "user", "content": prompt.environment_block(self.root)},
]
```

Why: the request is prefix + history + one volatile message. Everything before
the last element is identical to the previous call, which is exactly what a
prefix cache needs.

```python
self.system = prompt.system_prompt(self.root)
```

Why: built in `__init__`, not in `request()`. "Stable" has to mean stable.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> what branch am I on, and what does this project's AGENTS.md tell you to do?
you> now summarise nanoharness/prompt.py
python -m pytest -q test_step.py
```

Watch the usage line on the second turn: `in=... (cached N)` where N > 0 once the
prefix is long enough for the provider's cache.

## What you should see

```text
nanoharness step07 | openrouter | google/gemini-3.5-flash
project: /Users/you/.../step07_context_injection
  in=1811 (cached 0) out=41 cost=$0.000142
  in=2402 (cached 1792) out=88 cost=$0.000121
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/prompt.py` | new: `BASE`, `system_prompt`, `environment_block`, git helpers |
| `nanoharness/agent.py` | takes a `root`, builds the system prompt once, appends the environment block to the request only |
| `nanoharness/ui.py` | the usage line now shows `cached` tokens |
| `nanoharness/cli.py` | prints the project root in the banner |
| `AGENTS.md` | new: sample project instructions the harness picks up |
| `test_step.py` | rewritten: instruction file, git facts, prefix stability, transcript purity |
| `README.md` | this file |

## Gotchas

- Caching has a minimum size (about 1-2k tokens depending on the provider), so
  short conversations show `cached 0`. That is not a bug in the harness.
- The environment block is a `user` message because a second `system` message
  mid-conversation is rejected or ignored by several providers.
- `git branch --show-current` (not `rev-parse HEAD`) works in a repository that
  has no commits yet.
- Anything you add to `AGENTS.md` is paid for on every call. Keep it short.
