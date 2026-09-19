# Step 01: one raw HTTP call

**Goal:** see that an LLM call is nothing more than JSON in, JSON out.

**The idea:** before any SDK, agent or harness, there is a single HTTPS POST to
`/chat/completions`. The server keeps no memory between calls. If the model is
to "remember" anything, it must be in the `messages` list we send. Every later
step in this course is code that builds that list more cleverly.

## The code

One file: `raw_call.py`.

```python
APP_HEADERS = {
    "HTTP-Referer": "https://github.com/nitishsjsucs/harness-engineering-assignment-2",
    "X-Title": "nanoharness",
}
```

Why: OpenRouter uses these two optional headers to attribute requests to an app
(the app shows up in its rankings and in your activity page). They are plain
HTTP headers; the model never sees them.

```python
body = {
    "model": MODEL,
    "messages": [{"role": "user", "content": prompt}],
}
```

Why: this is the whole "state" of the conversation. One user message, no history.
Send the same body twice and the model has no idea it answered before.

```python
return httpx.post(f"{BASE_URL}/chat/completions", headers=headers, json=body, timeout=60)
```

Why: the entire transport. `httpx` serialises the dict to JSON and we get JSON back.

```python
cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
cost = usage.get("cost")  # OpenRouter adds this field; plain OpenAI does not
```

Why: OpenRouter's `usage` block tells you what the call cost in USD and how many
prompt tokens were served from the provider's prefix cache. We will watch
`cached_tokens` grow in step 07 once we keep the prompt prefix stable.

## Run it

```bash
source ../../.venv/bin/activate          # repo-root venv, see the top-level README
cp ../.env.example ../.env                # then put your OPENROUTER_API_KEY in ../.env
python raw_call.py "Explain an HTTP POST in one sentence."
HARNESS_MODEL=deepseek/deepseek-v4-flash python raw_call.py "Same question, different model."

# any OpenAI-compatible endpoint works: the URL and the bearer token are the only difference
HARNESS_BASE_URL=https://api.openai.com/v1 HARNESS_MODEL=gpt-5-mini \
  OPENROUTER_API_KEY="$OPENAI_API_KEY" python raw_call.py "Which model are you?"
python -m pytest -q test_step.py          # offline, httpx is mocked
```

## What you should see

```text
=== request headers ===
{ "Authorization": "Bearer sk-...redacted", "Content-Type": "application/json",
  "HTTP-Referer": "https://github.com/nitishsjsucs/...", "X-Title": "nanoharness" }
=== request body ===
{ "model": "deepseek/deepseek-v4-flash-0731:free", "messages": [ { "role": "user", "content": "..." } ] }
=== raw response JSON ===
{ "id": "gen-...", "choices": [ { "message": { "role": "assistant", "content": "..." } } ],
  "usage": { "prompt_tokens": 14, "completion_tokens": 22, "cost": 0.0000231, ... } }
=== reply ===
An HTTP POST sends data in the request body to a server ...
=== usage: prompt=14 completion=22 cached=0 cost=$0.000023 ===
```

Without a key it exits with code 2 and prints `Error: set OPENROUTER_API_KEY ...`.

## Diff from previous step

This is the first step. Files: `raw_call.py`, `test_step.py`, `README.md`.

## Gotchas

- A 401 means the key is missing or wrong; a 402 means the OpenRouter account has
  no credit (or use a `:free` model id); a 404 usually means a typo in the model id.
  The script prints the status and body instead of a stack trace.
- The key is masked when the headers are printed, so this is safe to record.
- `cost` is an OpenRouter extension of the OpenAI response format. Other
  OpenAI-compatible servers leave it out, so the code treats it as optional - a
  real call to OpenAI prints `cost=n/a` and real token counts.
- The default model is OpenRouter's free tier (`...:free`), which is rate limited
  to a few dozen requests a day per account. `HARNESS_MODEL` swaps in a paid one.
- This step has no provider table (that arrives in step 02). Pointing it at
  another endpoint is two environment variables, which is the whole point: the
  request is just JSON over HTTPS.
