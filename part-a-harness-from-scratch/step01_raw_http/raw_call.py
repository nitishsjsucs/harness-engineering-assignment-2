"""Step 01: one raw HTTP call to OpenRouter.

No SDK and no framework. We build a JSON body, POST it, and read JSON back.
The model keeps no state between calls: whatever it "knows" about the
conversation has to be inside the body we send.

    python raw_call.py "Explain what an HTTP POST is in one sentence."
"""
import json
import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv

# Read a .env file (searching upward from where you run the script) before
# looking at any environment variable below.
load_dotenv(find_dotenv(usecwd=True))

BASE_URL = os.getenv("HARNESS_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("HARNESS_MODEL", "google/gemini-3.5-flash")

# Optional OpenRouter headers. They attribute the traffic to our app on
# openrouter.ai (rankings, per-app analytics). The model never sees them.
APP_HEADERS = {
    "HTTP-Referer": "https://github.com/nitishsjsucs/harness-engineering-assignment-2",
    "X-Title": "nanoharness",
}


def build_request(prompt: str, api_key: str) -> tuple[dict, dict]:
    """Return (headers, body) for one chat completion."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **APP_HEADERS,
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    return headers, body


def post_chat(prompt: str, api_key: str) -> httpx.Response:
    headers, body = build_request(prompt, api_key)
    return httpx.post(f"{BASE_URL}/chat/completions", headers=headers, json=body, timeout=60)


def usage_line(data: dict) -> str:
    """One line with the numbers that matter for cost and caching."""
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    cost = usage.get("cost")  # OpenRouter adds this field; plain OpenAI does not
    cost_text = f"${cost:.6f}" if cost is not None else "n/a"
    return (
        f"usage: prompt={usage.get('prompt_tokens', 0)} "
        f"completion={usage.get('completion_tokens', 0)} "
        f"cached={cached} cost={cost_text}"
    )


def masked(headers: dict) -> dict:
    """Headers safe to print on screen (and on camera)."""
    return {k: ("Bearer sk-...redacted" if k == "Authorization" else v) for k, v in headers.items()}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    prompt = " ".join(args) or "Say hello and name the model you are, in one sentence."

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: set OPENROUTER_API_KEY (export it, or put it in a .env file).", file=sys.stderr)
        return 2

    headers, body = build_request(prompt, api_key)
    print("=== request headers ===")
    print(json.dumps(masked(headers), indent=2))
    print("=== request body ===")
    print(json.dumps(body, indent=2))

    try:
        response = post_chat(prompt, api_key)
    except httpx.HTTPError as err:
        print(f"Network error: {err}", file=sys.stderr)
        return 1
    if response.status_code >= 400:
        # OpenRouter explains most failures (bad key, unknown model, no credit) in the body.
        print(f"HTTP {response.status_code}: {response.text}", file=sys.stderr)
        return 1

    data = response.json()
    print("=== raw response JSON ===")
    print(json.dumps(data, indent=2))
    print("=== reply ===")
    print(data["choices"][0]["message"]["content"])
    print("=== " + usage_line(data) + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
