# Step 02: the SDK, and a transcript that is the memory

**Goal:** stop hand-rolling HTTP, and turn one call into a conversation.

**The idea:** the `openai` SDK speaks to any OpenAI-compatible server, so it
works with OpenRouter by changing `base_url`. Everything provider-specific moves
into `llm.py`; the REPL in `cli.py` only knows about a list of messages. That
list *is* the memory of the agent.

From here on the code lives in a `nanoharness/` package, the same package name
we install in step 15.

## The code

`nanoharness/llm.py` owns the provider switch:

```python
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "deepseek/deepseek-v4-flash-0731:free"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-3.5-flash"),
}
```

Why: one table, three endpoints, and the rest of the harness never learns which
one is in use. The default model is a `:free` id, so cloning this repository and
adding an OpenRouter key costs nothing; one `HARNESS_MODEL` swaps in a paid
model. OpenRouter is the default route - one key for many models, plus the
cost reporting and model fallback we use in step 15. `HARNESS_PROVIDER=openai`
and `HARNESS_PROVIDER=gemini` are direct routes for a key you already have; they
speak the same chat-completions API, so only this table changes.

```python
    if provider == "gemini":
        # Google's endpoint wants bare ids ("gemini-3.5-flash"), OpenRouter wants "google/...".
        model = model.removeprefix("google/")
    # Any route can be pointed elsewhere: a gateway, a proxy, Azure, a local server.
    base_url = os.getenv("HARNESS_BASE_URL", default_base_url)
```

Why: the only per-provider quirk in the whole file is Google's naming. Everything
else is one variable. `HARNESS_BASE_URL` overrides the endpoint for whichever
route you picked, which is how you put a gateway or a local server in front.

```python
client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], default_headers=headers)
```

Why: `default_headers` carries the `HTTP-Referer` / `X-Title` pair from step 01
on every request, so we never think about it again.

```python
def to_transcript(message) -> dict:
    out = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [call.model_dump(exclude_none=True, exclude={"index"}) for call in message.tool_calls]
```

Why: the response object carries provider extras (plain-text `reasoning`,
`refusal`, annotations). We store a minimal dict, because every message in the
transcript is re-sent on every later call and must stay valid for any model.
The one extra we keep is `reasoning_details` - Gemini 3 signs its tool calls
there and refuses a follow-up request that dropped the signature.

```python
transcript.append({"role": "user", "content": line})
reply, usage = llm.chat(transcript)
transcript.append(reply)
```

Why: that is the whole of "memory". No database, no vector store. Turn two is
turn one plus two more list elements.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness           # /exit to quit
python -m nanoharness --help
python -m pytest -q test_step.py
```

Ask it two related questions ("what is 2+2?" then "and times three?") to see
that the second answer depends on the first being in the list.

## What you should see

```text
nanoharness step02 | openrouter | deepseek/deepseek-v4-flash-0731:free | /exit to quit

you> what is 2+2?

4
[3 messages in memory | in=24 out=2 cost=$0.000008]

you> and times three?

12
[5 messages in memory | in=34 out=3 cost=$0.000011]
```

Without a key: `nanoharness: set OPENROUTER_API_KEY ...` and exit code 2.

## Diff from previous step

| File | Change |
|---|---|
| `raw_call.py` | removed (replaced by the package) |
| `nanoharness/__init__.py` | new, package marker |
| `nanoharness/__main__.py` | new, `python -m nanoharness` entry point |
| `nanoharness/llm.py` | new, client + provider switch + message cleaning |
| `nanoharness/cli.py` | new, the REPL |
| `test_step.py` | rewritten for the SDK, fakes `client.chat.completions.create` |
| `README.md` | this file |

## Gotchas

- `connect()` is cached with `lru_cache`, so the client is built once. Tests call
  `llm.connect.cache_clear()` after changing environment variables.
- `openai.APIError` covers timeouts, connection errors and HTTP errors. The REPL
  catches it, drops the unanswered user message and keeps running.
- Growing the list forever eventually exceeds the context window. Steps 07 and 13
  deal with that; for now, `/exit` is the garbage collector.
