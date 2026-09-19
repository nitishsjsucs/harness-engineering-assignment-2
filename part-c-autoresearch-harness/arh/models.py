"""Chat models for the headless proposer.

Two implementations behind one tiny interface (`complete`):

    ChatModel         the real thing: any tool-calling model on OpenRouter,
                      the OpenAI API, or Google AI Studio's OpenAI-compatible
                      endpoint. Pick with HARNESS_PROVIDER.
    ScriptedModel     a canned sequence of replies: no network, used by the
                      tests and by `arh loop --agent scripted`

Keeping the model behind an interface is what makes the whole harness testable
offline -- the loop, the tools and the guards never know which one they have.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

# Three OpenAI-compatible endpoints behind one client. OpenRouter is the
# documented default; the others exist so the harness is not tied to one
# vendor's availability (or to one person's billing account).
DEFAULTS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        # A ":free" model by default, so the whole harness can be run end to end
        # at zero cost. Free tier means ~50 requests per day across the account,
        # and one experiment costs at least one request -- see --max-requests.
        "model": "deepseek/deepseek-v4-flash-0731:free",
        "key_var": "OPENROUTER_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "key_var": "OPENAI_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash",
        "key_var": "GEMINI_API_KEY",
    },
}


class BudgetExceeded(RuntimeError):
    """The request cap was reached. Free tiers are a daily quota, not a tap."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    # The provider's own assistant message, appended to the conversation
    # verbatim: some models (Gemini) need their reasoning/signature fields
    # echoed back, and re-serialising by hand would drop them.
    raw: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class ScriptedModel:
    """Replays prepared replies, then stops proposing."""

    def __init__(self, replies: list[Reply]):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls += 1
        if not self.replies:
            return Reply(content="No further ideas.")
        return self.replies.pop(0)

    @property
    def name(self) -> str:
        return "scripted"

    @staticmethod
    def from_experiment_script(path) -> "ScriptedModel":
        """Build replies from a JSON list of hand-written experiments:

            [{"description": "...", "edits": [{"path": "train.py",
                                               "old": "...", "new": "..."}]}]

        Each entry becomes an edit_file turn followed by a run_experiment turn,
        so the scripted run exercises exactly the same tools, permission checks
        and engine path as a live model would.
        """
        steps = json.loads(open(path).read())
        replies = []
        for i, step in enumerate(steps):
            calls = [
                ToolCall(f"edit-{i}-{j}", step.get("tool", "edit_file"), edit)
                for j, edit in enumerate(step.get("edits", []))
            ]
            if calls:
                replies.append(Reply(content=step.get("thought", ""), tool_calls=calls))
            replies.append(
                Reply(tool_calls=[ToolCall(f"run-{i}", "run_experiment", {"description": step["description"]})])
            )
        return ScriptedModel(replies)


class ChatModel:
    """OpenAI-compatible chat completions with tool calling.

    One class for three providers, because they all speak the same wire format:
    only the base URL, the key variable and the default model differ. The
    provider comes from HARNESS_PROVIDER unless the caller names one.
    """

    def __init__(self, model=None, provider=None, base_url=None, api_key=None, fallbacks=None, client=None,
                 retries=3, max_requests=None):
        _load_dotenv()
        self.provider = provider or os.getenv("HARNESS_PROVIDER", "openrouter")
        cfg = DEFAULTS.get(self.provider) or DEFAULTS["openrouter"]
        self.model = model or os.getenv("HARNESS_MODEL") or cfg["model"]
        self.base_url = base_url or os.getenv("HARNESS_BASE_URL") or cfg["base_url"]
        self.retries = retries
        raw_fallbacks = fallbacks if fallbacks is not None else os.getenv("HARNESS_FALLBACK_MODELS", "")
        self.fallbacks = [m.strip() for m in (raw_fallbacks.split(",") if isinstance(raw_fallbacks, str) else raw_fallbacks) if m.strip()]
        self.max_requests = max_requests
        self.requests = 0
        self.tokens = 0
        self.cost = 0.0
        # OpenRouter prices each response (a free model reports a real 0.0);
        # other providers report nothing, and "n/a" is the honest answer there.
        self.cost_reported = False
        if client is not None:
            self.client = client
            return
        key = api_key or os.getenv(cfg["key_var"])
        if not key:
            raise RuntimeError(f"{cfg['key_var']} is not set (put it in .env or the environment)")
        from openai import OpenAI  # imported lazily: the engine never needs it

        self.client = OpenAI(api_key=key, base_url=self.base_url)

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise BudgetExceeded(f"request cap reached ({self.max_requests})")
        self.requests += 1
        kwargs = {"model": self.model, "messages": messages, "tools": tools}
        if self.provider == "openrouter":
            # Server-side fallback + the headers OpenRouter shows in its logs.
            if self.fallbacks:
                kwargs["extra_body"] = {"models": [self.model] + self.fallbacks}
            kwargs["extra_headers"] = {
                "HTTP-Referer": "https://github.com/nitishsjsucs/harness-engineering-assignment-2",
                "X-Title": "arh autoresearch harness",
            }
        response = self._with_retries(kwargs)
        message = response.choices[0].message
        raw = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
        self._account(getattr(response, "usage", None))
        return Reply(
            content=message.content or "",
            tool_calls=[
                ToolCall(c.id, c.function.name, _parse_args(c.function.arguments))
                for c in (message.tool_calls or [])
            ],
            raw=raw,
            usage=self.usage,
        )

    @property
    def usage(self) -> dict:
        """cost None means "the provider told us nothing"; cost 0.0 means the
        provider told us it was free. Those are different facts."""
        return {"requests": self.requests, "tokens": self.tokens, "cost": self.cost if self.cost_reported else None}

    def _account(self, usage) -> None:
        if usage is None:
            return
        self.tokens += int(getattr(usage, "total_tokens", 0) or 0)
        price = getattr(usage, "cost", None)
        if price is not None:
            self.cost += float(price)
            self.cost_reported = True

    # Retrying these just burns a daily quota faster: they will not heal in 2s.
    FATAL_STATUS = (401, 402, 403, 429)
    FATAL_NAMES = ("RateLimit", "Authentication", "PermissionDenied", "BadRequest", "NotFound")

    def _with_retries(self, kwargs: dict):
        for attempt in range(self.retries):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # network, rate limit, provider hiccup
                if attempt == self.retries - 1 or self._is_fatal(exc):
                    raise
                wait = 2 ** attempt
                print(f"[arh] model call failed ({exc.__class__.__name__}: {exc}); retrying in {wait}s", flush=True)
                time.sleep(wait)

    def _is_fatal(self, exc) -> bool:
        if getattr(exc, "status_code", None) in self.FATAL_STATUS:
            return True
        return any(name in exc.__class__.__name__ for name in self.FATAL_NAMES)


# The old name, kept so `from arh.models import OpenRouterModel` still works.
OpenRouterModel = ChatModel


def _parse_args(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    try:
        return json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"_raw": arguments}


def _load_dotenv() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path)
