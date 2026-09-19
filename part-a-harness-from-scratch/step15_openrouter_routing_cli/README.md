# Step 15: OpenRouter routing, cost, streaming, and a real command

**Goal:** the things you only want once the harness works - a model that fails
over, a bill you can see, output that appears as it is generated, and an
installable `nanoharness` command.

**The idea:** four production features that all live at the edges of the loop.

1. **Server-side fallback**: `extra_body={"models": [primary, *fallbacks]}`.
   OpenRouter tries the next model inside the same request if the first one
   errors or is rate limited.
2. **Provider preferences**: `extra_body={"provider": {...}}` to sort by price or
   pin an upstream.
3. **A cost ledger**: OpenRouter reports `usage.cost` per call, so `/cost` is a
   sum, not an estimate from a price list we would have to maintain.
4. **Streaming**: text arrives token by token; the assembled message is
   identical, so the agent loop does not change.

And packaging: `pip install -e .` puts `nanoharness` on your PATH.

## The code

`nanoharness/llm.py`:

```python
chain = fallback_models(primary=model)
if chain:
    body["models"] = [model, *chain]
```

Why: a retry loop on our side costs a round trip and cannot see that a provider
is down. OpenRouter already knows, and does it server-side. Verified live: asking
for `qwen/qwen3.8-27b:free` (rate limited upstream that afternoon) with
`nvidia/nemotron-3.5-lightning:free` behind it returned an answer, and the
response's model id was the *fallback*. What the chain does **not** cover is a
model id that does not exist - see the gotchas.

```python
"model": getattr(response, "model", None),
```

Why: with a fallback chain the answer is not always from the model you asked for.
The usage line says `served by deepseek/deepseek-v4-flash` when the id differs,
and the ledger groups by the model that actually answered. (Live on OpenAI this
shows `served by gpt-5-mini-2025-08-07`: the dated snapshot behind the alias, not
a fallback.)

```python
slot = partial_calls.setdefault(
    piece.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
)
...
slot["function"]["arguments"] += piece.function.arguments
```

Why: streamed tool calls arrive as fragments addressed by `index`, and the
arguments are a JSON string split at arbitrary points. Reassembling them here
means the agent loop never learns that streaming exists.

```python
kwargs["stream_options"] = {"include_usage": True}  # or the last chunk has no usage at all
```

Why: without it a streamed response reports no tokens and no cost, and `/cost`
silently reads zero.

`nanoharness/cost.py`:

```python
    @property
    def total(self) -> float | None:
        """USD across the priced calls, or None when nothing was priced at all."""
        return sum(call["cost"] for call in self.priced) if self.priced else None
```

Why: OpenAI and Google report tokens but never a price. Summing their calls as
`0.0` would print a confident `$0.000000`, which is a lie; `None` becomes `n/a`
plus the line "this provider reports no cost; the token counts above are exact".
`cached_tokens` is treated the same way: absent means unknown, not zero.

`pyproject.toml`:

```toml
[project.scripts]
nanoharness = "nanoharness.cli:main"
```

Why: this one line is the difference between a folder of scripts and a tool. The
installer writes a small wrapper that imports `nanoharness.cli` and calls
`main()`, and `sys.exit` receives its return code.

## Run it

```bash
source ../../.venv/bin/activate
pip install -e .
nanoharness --help
nanoharness --version
cd /tmp/some-project && nanoharness           # works anywhere now
you> /model deepseek/deepseek-v4-pro
you> /cost
HARNESS_PROVIDER_SORT=price nanoharness       # cheapest provider for the model
HARNESS_PROVIDER=openai HARNESS_MODEL=gpt-5-mini nanoharness   # same harness, an OpenAI key
nanoharness --no-stream                        # wait for the whole reply
python -m pytest -q test_step.py
```

## What you should see

A real OpenRouter capture on the free default (2026-09-19, five model calls):

```text
nanoharness 0.15.0 | openrouter | deepseek/deepseek-v4-flash-0731:free | permissions: default
fallbacks: nvidia/nemotron-3.5-lightning:free
sandbox: seatbelt (write only inside the project, no network)
...
  in=1616 (cached 1212) out=157 cost=$0.000000
  in=1776 (cached 1776) out=67 cost=$0.000000
you> /cost
  model                                calls       in  cached    out       cost
  deepseek/deepseek-v4-flash-0731:free     5     9228    8563    699   0.000000
  total                                    5                           0.000000
```

`cost 0.000000` is a *reported* zero (a free model really costs nothing), which
is not the same as the `n/a` below - that one means the provider never said.

The same session on the OpenAI route (also a real capture, 2026-09-19):

```text
nanoharness 0.15.0 | openai | gpt-5-mini | permissions: default
  in=1435 (cached 0) out=27 cost=n/a served by gpt-5-mini-2025-08-07
you> /cost
  model                          calls       in  cached    out       cost
  gpt-5-mini-2025-08-07              7     9323       0    785        n/a
  total                              7                                n/a
  this provider reports no cost; the token counts above are exact
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/llm.py` | `fallback_models`, `provider_preferences`, `extra_body` (OpenRouter only), streaming (`stream_chat`), served model in usage, `cost`/`cached_tokens` left as None when unreported |
| `nanoharness/cost.py` | new: the per-session `Ledger`, which reports `n/a` instead of inventing a zero |
| `nanoharness/agent.py` | `model`, `stream` and shared `ledger`; records every call; streams through the UI |
| `nanoharness/ui.py` | `stream_text` / `end_stream` / `stop_thinking`, usage line names the serving model |
| `nanoharness/commands.py` | `/cost` and `/model` |
| `nanoharness/cli.py` | `--model`, `--no-stream`, `--version`, banner with fallbacks, cost on exit |
| `nanoharness/__init__.py` | `__version__` |
| `pyproject.toml` | new: dependencies and the `nanoharness` console script |
| `test_step.py` | rewritten: routing extras, streaming assembly, ledger, `/cost`, `/model`, packaging |
| `README.md` | this file |

## Gotchas

- **A fallback chain is not a spell-checker.** OpenRouter validates every id in
  `models` before it routes, so one typo fails the whole request:
  `400 - deepseek/does-not-exist:free is not a valid model ID`, and the fallback
  is never tried. The chain covers *runtime* failures - a provider erroring,
  timing out or rate limiting you - which is exactly what the live test above
  showed. Check your ids at startup; do not rely on the chain to hide them.
- **The free tier is rate limited.** The `:free` defaults cost nothing but allow
  only a few dozen requests a day per account, and one agent turn is five or six
  requests. A `429` from OpenRouter arrives as an `openai.APIError`, so the REPL
  prints `[api error] ...` and stays alive; wait, or switch with `/model` to a
  paid id.
- **On the OpenAI route** (`HARNESS_PROVIDER=openai`, `HARNESS_MODEL=gpt-5-mini`)
  three of this step's features simply do not apply, and the harness says so
  rather than faking them: `extra_body` is empty (the `models` fallback chain and
  `provider` preferences are OpenRouter extensions that OpenAI rejects as unknown
  fields), `/cost` prints `n/a`, and the banner still lists the configured
  fallbacks but they are never sent. Streaming, tools, sessions, permissions and
  the sandbox all work unchanged.
- **gpt-5 family quirks.** Nothing had to change in the harness, because it never
  sends `temperature`, `top_p` or `max_tokens` - the three parameters gpt-5 models
  reject or rename (`max_completion_tokens`). If you add them, add them per
  provider. Note also that gpt-5 spends invisible reasoning tokens: a one-sentence
  reply billed 114 completion tokens, 64 of them reasoning, so a "cheap" turn is
  not as cheap as the visible text suggests.
- `pip install -e .` from this directory installs the *step 15* code. Running
  `python -m nanoharness` inside another step directory still uses that step's
  copy, because the current directory wins on `sys.path`.
- `extra_body` is OpenRouter-specific. `extra_body({"provider": "gemini"}, ...)`
  returns `{}` so the direct Google endpoint is not sent fields it would reject.
- Streaming and `reasoning_details` do not mix well: the harness keeps signatures
  from non-streamed replies, and Gemini tool calls made while streaming may lose
  them. If a model complains about a missing thought signature, run with
  `--no-stream`.
- A fallback only triggers on provider errors, not on a bad answer. Quality
  fallback is an eval problem, not a routing one.

## Where to go next

The loop is done. Everything after this is either a different backend (an agent
SDK, a harness server) or a new capability bolted onto the same six lines: MCP
clients, hooks, parallel tools, evals. Part B and Part C of this repository take
two of those roads.
