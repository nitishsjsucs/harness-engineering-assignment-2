#!/usr/bin/env python3
"""PostToolUse hook: after editing an editable file, remind the assistant that
an unmeasured edit is not an experiment.

This is the cheapest possible nudge against the most common failure mode of an
autoresearch session: stacking three clever changes and then measuring once, so
nobody can tell which one worked.
"""

from task_lookup import add_context, allow, find_task, matches, read_event, relative_to, tool_path

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def main():
    event = read_event()
    if event is None or event.get("tool_name") not in EDIT_TOOLS:
        allow()
    path = tool_path(event)
    if not path:
        allow()
    try:
        task_dir, state = find_task(path)
    except RuntimeError:
        allow()  # a PostToolUse hook must never block work; the engine will catch it
    if task_dir is None or not matches(relative_to(task_dir, path), state.get("editable")):
        allow()

    add_context(
        "PostToolUse",
        "arh: you edited an editable file of task '{0}'. When this one change is complete, measure it with "
        "`arh run -C {1} -m \"<what you changed and why>\"`. Do not stack a second idea on top of an "
        "unmeasured one: the harness can only attribute a score to the diff it runs.".format(
            state.get("task", "task"), task_dir
        ),
    )


if __name__ == "__main__":
    main()
