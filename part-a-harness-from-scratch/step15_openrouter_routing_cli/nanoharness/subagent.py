"""Subagents: a second context window that you are allowed to throw away.

"Find where the retry logic lives" can cost thirty tool results and teach the
main conversation one sentence. A subagent does that work in its own empty
transcript and returns only the answer, so the parent pays for the sentence.

The toolset is the safety mechanism. No `task` means no recursion; no
write_file/edit_file/write_todos means a subagent cannot change the project or
the parent's plan.
"""
from .registry import tool

SUBAGENT_TOOLS = ("bash", "read_file", "list_dir", "load_skill")

SUBAGENT_NOTE = (
    "# You are a subagent\n"
    "You were given one self-contained task by the main agent. You cannot edit files, "
    "keep a plan, or start further subagents, and nobody will answer follow-up questions.\n"
    "Investigate with your tools, then reply with the findings themselves: exact paths, "
    "line numbers, commands and error text. Your reply is the only thing that reaches the "
    "main conversation, so never answer with 'I looked at it' - say what you found."
)


@tool
def task(description: str, prompt: str, agent=None) -> str:
    """Hand a self-contained investigation to a subagent that has its own empty context and
    read-only tools. Use it for searching, reading and summarising when the details would
    otherwise fill this conversation. The subagent cannot edit files; do that yourself
    afterwards with what it reports.

    Args:
        description: A short label for the terminal, three to six words.
        prompt: Complete instructions for the subagent. It sees none of this conversation,
            so repeat every fact it needs, and say exactly what to report back.
    """
    if agent is None:
        return "Error: the task tool can only run inside an agent."
    agent.ui.subagent_start(description)
    child = agent.spawn_child(tools=list(SUBAGENT_TOOLS), note=SUBAGENT_NOTE)
    answer = child.run(prompt)
    agent.ui.subagent_done(description, len(child.messages))
    return answer or "(the subagent finished without an answer)"
