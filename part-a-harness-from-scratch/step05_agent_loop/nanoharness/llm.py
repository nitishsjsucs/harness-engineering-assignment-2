"""Model access: the only module that knows which provider we talk to.

The rest of nanoharness calls `chat(messages, tools)` and gets back a plain
dict it can store in the transcript and send again on the next call.
"""
import functools
import os

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

load_dotenv(find_dotenv(usecwd=True))

APP_HEADERS = {
    "HTTP-Referer": "https://github.com/nitishsjsucs/harness-engineering-assignment-2",
    "X-Title": "nanoharness",
}

# provider -> (base URL, env var that holds the key, default model id)
# OpenRouter is the default: one key, many models, cost reporting and model fallback.
# The other two are direct routes, for a key you already have.
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "google/gemini-3.5-flash"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-3.5-flash"),
}


class ConfigError(RuntimeError):
    """The harness cannot reach a model (unknown provider, missing key)."""


def settings() -> dict:
    """Resolve provider, endpoint, key and model from the environment."""
    provider = os.getenv("HARNESS_PROVIDER", "openrouter").strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"HARNESS_PROVIDER must be one of {sorted(PROVIDERS)}, got {provider!r}")
    default_base_url, key_env, default_model = PROVIDERS[provider]
    api_key = os.getenv(key_env)
    if not api_key:
        raise ConfigError(f"set {key_env} (export it, or put it in a .env file) to use provider '{provider}'")
    model = os.getenv("HARNESS_MODEL", default_model)
    if provider == "gemini":
        # Google's endpoint wants bare ids ("gemini-3.5-flash"), OpenRouter wants "google/...".
        model = model.removeprefix("google/")
    # Any route can be pointed elsewhere: a gateway, a proxy, Azure, a local server.
    base_url = os.getenv("HARNESS_BASE_URL", default_base_url)
    return {"provider": provider, "base_url": base_url, "api_key": api_key, "model": model}


@functools.lru_cache(maxsize=1)
def connect() -> tuple[dict, OpenAI]:
    """Build the client once. The OpenAI SDK speaks to any OpenAI-compatible server."""
    cfg = settings()
    headers = APP_HEADERS if cfg["provider"] == "openrouter" else None
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], default_headers=headers)
    return cfg, client


def chat(messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, dict]:
    """One model call. Returns (assistant message for the transcript, usage numbers)."""
    cfg, client = connect()
    kwargs = {"model": cfg["model"], "messages": messages}
    if tools:
        kwargs["tools"] = tools
    response = client.chat.completions.create(**kwargs)
    return to_transcript(response.choices[0].message), usage_of(response)


def to_transcript(message) -> dict:
    """Keep only what we can safely send back: role, content, tool_calls.

    Providers attach extras (plain-text `reasoning`, refusal flags, ...). We drop
    them so the transcript stays small and valid for any model. The one extra we
    keep is `reasoning_details`: Gemini 3 signs its tool calls there and rejects
    a follow-up request that loses the signature.
    """
    out = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [call.model_dump(exclude_none=True, exclude={"index"}) for call in message.tool_calls]
    elif out["content"] is None:
        out["content"] = ""
    details = getattr(message, "reasoning_details", None)
    if details:
        out["reasoning_details"] = details
    return out


def usage_of(response) -> dict:
    """Flatten the usage block. `cost` only exists on OpenRouter responses."""
    usage = response.usage.model_dump() if response.usage else {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "cached_tokens": details.get("cached_tokens") or 0,
        "cost": usage.get("cost"),
    }


def format_usage(usage: dict) -> str:
    cost = usage.get("cost")
    cost_text = f"${cost:.6f}" if cost is not None else "n/a"
    return f"in={usage['prompt_tokens']} out={usage['completion_tokens']} cost={cost_text}"
