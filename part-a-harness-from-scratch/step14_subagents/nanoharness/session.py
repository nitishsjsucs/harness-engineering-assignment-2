"""Sessions: an append-only JSONL log of everything that entered the transcript.

Append-only is the point. We never rewrite the file, so a crash can only ever
lose the last line. Things that *remove* messages (a rewind) are written as their
own event and applied again when the log is replayed.

    .nanoharness/sessions/20260919-142530-a1b2.jsonl
      {"kind": "meta", "at": "...", "cwd": "...", "model": "..."}
      {"kind": "message", "at": "...", "message": {"role": "user", ...}}
      {"kind": "rewind", "at": "...", "keep": 4}
      {"kind": "compact", "at": "...", "cut": 12, "summary": "..."}
"""
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SESSIONS_RELATIVE = Path(".nanoharness") / "sessions"


class Restored(NamedTuple):
    """What a replay gives back: the transcript and the compaction summary."""

    messages: list[dict]
    summary: str | None


def directory(root: Path | str) -> Path:
    return Path(root) / SESSIONS_RELATIVE


class Session:
    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def new(cls, root: Path | str) -> "Session":
        """A new id now; the file appears on the first record()."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return cls(directory(root) / f"{stamp}-{secrets.token_hex(2)}.jsonl")

    @property
    def id(self) -> str:
        return self.path.stem

    def record(self, kind: str, **data) -> None:
        """Append one event. A logging problem must never take the conversation down."""
        event = {"kind": kind, "at": datetime.now().isoformat(timespec="seconds"), **data}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a half-written last line after a kill -9
        return events

    def replay(self) -> Restored:
        """Rebuild the transcript by applying the events in order."""
        messages: list[dict] = []
        summary: str | None = None
        for event in self.events():
            kind = event.get("kind")
            if kind == "message" and isinstance(event.get("message"), dict):
                messages.append(event["message"])
            elif kind == "rewind":
                del messages[int(event.get("keep", len(messages))) :]
            elif kind == "compact":
                summary = event.get("summary")
                del messages[: int(event.get("cut", 0))]
        return Restored(repair(messages), summary)

    def summary(self) -> dict:
        """What /sessions shows: when, how big, and how it started."""
        messages = self.replay().messages
        first_user = next((m for m in messages if m.get("role") == "user"), None)
        started = self.path.stat().st_mtime if self.path.exists() else 0
        return {
            "id": self.id,
            "messages": len(messages),
            "when": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") if started else "?",
            "first": (str(first_user["content"])[:60] if first_user else "(empty)"),
        }


def list_sessions(root: Path | str, limit: int = 10) -> list[Session]:
    """Newest first."""
    folder = directory(root)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [Session(path) for path in files[:limit]]


def latest(root: Path | str) -> Session | None:
    sessions = list_sessions(root, limit=1)
    return sessions[0] if sessions else None


def find(root: Path | str, session_id: str) -> Session | None:
    """Accept a prefix, because nobody types a full timestamp id."""
    for session in list_sessions(root, limit=1000):
        if session.id == session_id or session.id.startswith(session_id):
            return session
    return None


def repair(messages: list[dict]) -> list[dict]:
    """Answer tool calls that never got a result.

    A crash (or Ctrl-C at the wrong moment) can leave an assistant message whose
    tool calls have no matching role=tool messages. Every provider rejects that,
    so a resumed session would be dead on arrival. We invent the missing results.
    """
    fixed: list[dict] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        fixed.append(message)
        index += 1
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        answered = set()
        while index < len(messages) and messages[index].get("role") == "tool":
            answered.add(messages[index].get("tool_call_id"))
            fixed.append(messages[index])
            index += 1
        for call in message["tool_calls"]:
            if call["id"] not in answered:
                fixed.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": "Error: this tool call was interrupted and never ran. Try it again if you still need it.",
                    }
                )
    return fixed
