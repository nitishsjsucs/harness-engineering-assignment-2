"""Keeping a long conversation inside the context window.

Two mechanisms, cheapest first.

1. Trimming. Tool results are enormous and go stale fast: after the turn that
   asked for them is over, the file has usually been read, edited and re-read.
   Old results are replaced by a one-line stub.
2. Compaction. When the estimate crosses a fraction of the context window, the
   older part of the transcript is summarised by a tool-less model call and the
   summary is folded into the system prompt.

Both rewrite history, which costs a cache miss, so both happen as rarely as
possible: trimming once per turn, compaction only over the threshold. The cut is
always at a user message, so a tool call is never separated from its result.
"""
import json
import os

from . import llm

CONTEXT_WINDOW = int(os.getenv("HARNESS_CONTEXT_WINDOW", "128000"))
COMPACT_AT = 0.75  # fraction of the window that triggers automatic compaction
STUB_OVER = 400  # only results longer than this are worth stubbing
KEEP_RECENT_TURNS = 1  # turns whose tool results stay whole

SUMMARY_SYSTEM = (
    "You compress a coding session so that another agent can continue it without the "
    "original transcript. Write dense notes under these headings:\n"
    "1. Goal - what the user asked for, in their words.\n"
    "2. Facts learned - file paths, function names, commands that worked, error messages.\n"
    "3. Changes made - every file created or edited and what changed in it.\n"
    "4. Open threads - what is unfinished, what was about to happen next.\n"
    "Keep every identifier exactly as written. No praise, no meta-commentary."
)


def estimate_tokens(messages: list[dict]) -> int:
    """Four characters per token is wrong in detail and right enough to budget with."""
    return len(json.dumps(messages, ensure_ascii=False, default=str)) // 4


def trim_old_tool_results(messages: list[dict]) -> int:
    """Stub the tool results of finished turns. Returns how many were stubbed."""
    boundary = turn_start(messages, KEEP_RECENT_TURNS)
    if boundary is None:
        return 0
    trimmed = 0
    for index in range(boundary):
        message = messages[index]
        content = message.get("content") or ""
        if message.get("role") != "tool" or len(content) <= STUB_OVER:
            continue
        messages[index] = {
            **message,
            "content": f"[{len(content)} characters of tool output from an earlier turn, "
            "trimmed by the harness. Run the tool again if you need it.]",
        }
        trimmed += 1
    return trimmed


def turn_start(messages: list[dict], nth_from_end: int) -> int | None:
    """Index of the user message that starts the n-th last turn (n=1 is the current one).

    None when there is nothing older than that, which means there is nothing to
    trim or compact yet. Cutting here is what keeps a tool call together with its
    result: a user message never sits between the two.
    """
    starts = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    if len(starts) <= nth_from_end:
        return None
    return starts[len(starts) - nth_from_end]


def over_budget(agent) -> bool:
    return estimate_tokens(agent.request()) > int(COMPACT_AT * CONTEXT_WINDOW)


def compact(agent, force: bool = False) -> str | None:
    """Summarise everything before the last turn. Returns the summary, or None."""
    if not force and not over_budget(agent):
        return None
    cut = turn_start(agent.messages, KEEP_RECENT_TURNS)
    if not cut:  # None, or 0 = the whole transcript is the current turn
        return None

    summary = summarise(agent.messages[:cut], agent.summary)
    agent.summary = summary
    agent.messages = agent.messages[cut:]
    if agent.session:
        # Append-only again: replaying the log applies the same cut.
        agent.session.record("compact", cut=cut, summary=summary)
    agent.ui.info(f"[compacted {cut} messages into a summary; {len(agent.messages)} left]")
    return summary


def summarise(messages: list[dict], previous: str | None = None) -> str:
    """One model call with no tools: the summariser can only write."""
    parts = []
    if previous:
        parts.append(f"Summary of even older messages:\n{previous}\n")
    parts.append(transcript_text(messages))
    reply, _usage = llm.chat(
        [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "\n".join(parts)}]
    )
    return (reply.get("content") or "").strip() or "(the summariser returned nothing)"


def transcript_text(messages: list[dict], result_limit: int = 1000) -> str:
    """Flatten messages to plain text; tool calls become readable lines.

    Sending the raw messages would re-send tool-call structures we would then
    have to keep valid. Text is easier to truncate and impossible to malform.
    """
    lines = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                lines.append(f"assistant called {call['function']['name']}({call['function']['arguments']})")
            if content:
                lines.append(f"assistant: {content}")
        elif role == "tool":
            lines.append(f"tool result: {content[:result_limit]}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)
