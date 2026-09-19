"""A plan the model keeps up to date, stored in the harness instead of the chat.

Why not just let the model write a plan in its answer? Because that plan scrolls
out of the model's attention after a few tool results. Keeping the list in
harness state and re-injecting it with the environment block means the current
plan is always the last thing the model reads before it decides what to do next.
"""
from typing import Literal, TypedDict

from .registry import tool

Status = Literal["pending", "in_progress", "completed"]

MARKS = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}


class Todo(TypedDict):
    """One item of the plan. The TypedDict is what the schema is derived from."""

    content: str
    status: Status


@tool
def write_todos(todos: list[Todo], agent) -> str:
    """Replace the whole todo list with a new one. Use this for any task with three or
    more steps: write the plan first, then keep it current. Mark exactly one item as
    in_progress while you work on it, and mark it completed as soon as it is done.

    Args:
        todos: The complete new list, in order. Each item is an object with
            content (what to do) and status (pending, in_progress or completed).
    """
    problem = validate(todos)
    if problem:
        return f"Error: {problem}"
    agent.todos = [{"content": str(item["content"]), "status": item["status"]} for item in todos]
    return "Plan updated:\n" + render(agent.todos)


def validate(todos) -> str | None:
    """Return a message the model can act on, or None when the list is fine."""
    if not isinstance(todos, list):
        return "todos must be a list of objects with content and status."
    in_progress = 0
    for index, item in enumerate(todos):
        if not isinstance(item, dict):
            return f"item {index} is not an object with content and status."
        if not str(item.get("content", "")).strip():
            return f"item {index} has an empty content field."
        status = item.get("status")
        if status not in MARKS:
            return f"item {index} has status {status!r}; use pending, in_progress or completed."
        in_progress += status == "in_progress"
    if in_progress > 1:
        return f"{in_progress} items are in_progress; exactly one item may be in progress at a time."
    return None


def render(todos: list[dict]) -> str:
    """The checklist as the model (and the user) sees it."""
    return "\n".join(f"{MARKS[item['status']]} {item['content']}" for item in todos)
