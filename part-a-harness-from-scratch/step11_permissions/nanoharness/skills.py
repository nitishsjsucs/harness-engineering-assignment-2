"""Skills: instructions that only enter the context when they are needed.

A skill is a directory with a SKILL.md file. The YAML front matter (name,
description) is cheap and goes in the system prompt; the body can be as long as
it likes, because the model only pays for it when it calls load_skill.

    skills/
      code-explainer/
        SKILL.md      ---\\nname: code-explainer\\ndescription: ...\\n---\\n<body>
"""
from pathlib import Path

import yaml

from .registry import tool

# Searched in order; the first directory that defines a name wins.
SKILL_DIRS = (".nanoharness/skills", "skills")


def discover(root: Path | str) -> dict[str, dict]:
    """Find every skill under the project root. Never raises on a malformed file."""
    found: dict[str, dict] = {}
    for relative in SKILL_DIRS:
        for skill_file in sorted(Path(root, relative).glob("*/SKILL.md")):
            try:
                meta, body = parse(skill_file.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue  # a broken skill must not stop the harness from starting
            name = str(meta.get("name") or skill_file.parent.name)
            found.setdefault(
                name,
                {
                    "name": name,
                    "description": str(meta.get("description", "")).strip(),
                    "path": skill_file,
                    "body": body,
                },
            )
    return found


def parse(text: str) -> tuple[dict, str]:
    """Split "---\\nyaml\\n---\\nbody" into (metadata, body)."""
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        return yaml.safe_load(front) or {}, body.strip()
    return {}, text.strip()


def catalog(skills: dict[str, dict]) -> str:
    """The only part of a skill that costs tokens on every call."""
    if not skills:
        return ""
    lines = [f"- {s['name']}: {s['description']}" for s in skills.values()]
    return (
        "# Skills\n"
        "These skills hold detailed instructions for specific jobs. If one of them fits the task, "
        "call load_skill with its name and follow what it says before doing anything else.\n"
        + "\n".join(lines)
    )


@tool
def load_skill(name: str) -> str:
    """Load the full instructions of one of the skills listed in the system prompt.

    Args:
        name: The skill name exactly as it is listed.
    """
    skills = discover(Path.cwd())
    skill = skills.get(name)
    if skill is None:
        available = ", ".join(skills) or "none"
        return f"Error: no skill named {name!r}. Available skills: {available}."
    return (
        f"# Skill: {skill['name']}\n"
        f"(files for this skill live in {skill['path'].parent})\n\n"
        f"{skill['body']}"
    )
