#!/usr/bin/env python3
"""PreToolUse hook: inside an active arh task, only editable files may be written.

The engine already refuses to score an experiment that touched frozen files.
This hook moves that refusal one step earlier, to the moment the edit is
attempted, so the assistant learns the rule instead of burning an experiment on
it. Both layers exist on purpose: the hook is convenience, the engine is truth
(the engine still catches edits made through Bash, which no hook matcher sees).

Fail closed: if the payload or the task state cannot be read, deny.
"""

from task_lookup import allow, deny, find_task, matches, read_event, relative_to, tool_path

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def main():
    event = read_event()
    if event is None:
        deny("autoresearch hook: could not parse the tool payload, so the edit is blocked (fail closed).")
    if event.get("tool_name") not in EDIT_TOOLS:
        allow()

    path = tool_path(event)
    if not path:
        deny("autoresearch hook: no file path in the tool input, so the edit is blocked (fail closed).")

    try:
        task_dir, state = find_task(path)
    except RuntimeError as exc:
        deny("autoresearch hook: " + str(exc) + " -- blocked (fail closed).")
    if task_dir is None:
        allow()  # not part of an autoresearch task: none of our business

    rel = relative_to(task_dir, path)
    task = state.get("task", "task")
    if rel.startswith(".arh/"):
        deny(
            "autoresearch: {0} is the harness's own ledger/state for task '{1}'. It is append-only "
            "evidence of what was measured. Use `arh status`, `arh report` or `arh guard` instead.".format(rel, task)
        )
    if matches(rel, state.get("editable")):
        allow()

    why = "a frozen evaluation file" if matches(rel, state.get("frozen")) else "not on the editable list"
    deny(
        "autoresearch: {0} is {1} for task '{2}'. Only {3} may change during an experiment. If the change "
        "really belongs in the frozen part of the task, stop the loop and agree it with a human first -- "
        "editing it mid-run invalidates every score already in the ledger.".format(
            rel, why, task, ", ".join(state.get("editable") or [])
        )
    )


if __name__ == "__main__":
    main()
