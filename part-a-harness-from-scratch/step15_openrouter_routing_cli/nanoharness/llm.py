"""Model access: the only module that knows which provider we talk to.

The rest of nanoharness calls `chat(messages, tools)` and gets back a plain
dict it can store in the transcript and send again on the next call.

Step 15 adds the three things OpenRouter gives us that a single provider cannot:
a server-side fallback chain, provider routing preferences, and a cost per call.
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
# The default model there is free-tier, so the whole course runs at zero cost;
# swap it for a paid id with HARNESS_MODEL. The other two are direct routes.
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "deepseek/deepseek-v4-flash-0731:free"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-3.5-flash"),
}

DEFAULT_FALLBACKS = "nvidia/nemotron-3.5-lightning:free"  # free too, so the safety net costs nothing


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


def fallback_models(primary: str | None = None) -> list[str]:
    """The models OpenRouter should try if the first one fails."""
    listed = [name.strip() for name in os.getenv("HARNESS_FALLBACK_MODELS", DEFAULT_FALLBACKS).split(",")]
    return [name for name in listed if name and name != primary]


def provider_preferences() -> dict:
    """OpenRouter provider routing: which upstream serves the model, and in what order."""
    preferences: dict = {}
    sort = os.getenv("HARNESS_PROVIDER_SORT", "").strip()  # price | throughput | latency
    if sort:
        preferences["sort"] = sort
    order = [name.strip() for name in os.getenv("HARNESS_PROVIDER_ORDER", "").split(",") if name.strip()]
    if order:
        preferences["order"] = order
    if os.getenv("HARNESS_PROVIDER_ALLOW_FALLBACKS", "").strip() == "0":
        preferences["allow_fallbacks"] = False
    return preferences


def extra_body(cfg: dict, model: str) -> dict:
    """OpenRouter-only request extras. Any other server would reject them."""
    if cfg["provider"] != "openrouter":
        return {}
    body: dict = {}
    chain = fallback_models(primary=model)
    if chain:
        # Server-side fallback: if the first model errors or is rate limited,
        # OpenRouter tries the next one inside the same request.
        body["models"] = [model, *chain]
    preferences = provider_preferences()
    if preferences:
        body["provider"] = preferences
    return body


def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None, on_text=None):
    """One model call. Returns (assistant message for the transcript, usage numbers).

    Passing `on_text` switches to streaming: the callback gets text as it arrives
    and the assembled message is returned at the end, exactly as in the
    non-streaming case, so the loop above does not change.
    """
    cfg, client = connect()
    kwargs: dict = {"model": model or cfg["model"], "messages": messages}
    if tools:
        kwargs["tools"] = tools
    extras = extra_body(cfg, kwargs["model"])
    if extras:
        kwargs["extra_body"] = extras
    if on_text is None:
        response = client.chat.completions.create(**kwargs)
        return to_transcript(response.choices[0].message), usage_of(response)

    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}  # or the last chunk has no usage at all
    return stream_chat(client, kwargs, on_text)


def stream_chat(client, kwargs: dict, on_text) -> tuple[dict, dict]:
    """Reassemble streamed deltas into the same (message, usage) pair."""
    text_parts: list[str] = []
    partial_calls: dict[int, dict] = {}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": None, "cost": None, "model": kwargs["model"]}

    for chunk in client.chat.completions.create(**kwargs):
        if getattr(chunk, "usage", None):
            usage = usage_of(chunk)  # OpenRouter sends usage (and cost) in the final chunk
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if delta.content:
            text_parts.append(delta.content)
            on_text(delta.content)
        for piece in delta.tool_calls or []:
            # Tool calls arrive in fragments, addressed by index, not by id.
            slot = partial_calls.setdefault(
                piece.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if piece.id:
                slot["id"] = piece.id
            if piece.function and piece.function.name:
                slot["function"]["name"] = piece.function.name
            if piece.function and piece.function.arguments:
                slot["function"]["arguments"] += piece.function.arguments

    message: dict = {"role": "assistant", "content": "".join(text_parts) or None}
    if partial_calls:
        message["tool_calls"] = [partial_calls[index] for index in sorted(partial_calls)]
    elif message["content"] is None:
        message["content"] = ""
    return message, usage


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
    """Flatten the usage block.

    `cost` and `cached_tokens` stay None when the provider did not report them:
    OpenAI and Google price their own bills and send no cost at all, and
    "not reported" must not be displayed or summed as a confident zero.
    """
    usage = response.usage.model_dump() if response.usage else {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "cached_tokens": details.get("cached_tokens"),
        "cost": usage.get("cost"),  # OpenRouter only
        # Which model actually answered: with a fallback chain it is not always the first.
        "model": getattr(response, "model", None),
    }


def format_usage(usage: dict) -> str:
    cost = usage.get("cost")
    cost_text = f"${cost:.6f}" if cost is not None else "n/a"
    return f"in={usage['prompt_tokens']} out={usage['completion_tokens']} cost={cost_text}"
