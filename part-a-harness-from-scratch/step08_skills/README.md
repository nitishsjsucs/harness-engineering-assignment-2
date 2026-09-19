# Step 08: skills, loaded on demand

**Goal:** give the agent long, specific playbooks without paying for them on
every call.

**The idea:** a skill is a folder with a `SKILL.md`. Its YAML front matter
(`name`, `description`) is one line in the system prompt - that is the whole
advertisement. The body only enters the context when the model calls
`load_skill(name)`. Ten skills cost about ten lines of prompt; the bodies can be
pages long.

## The code

`nanoharness/skills.py`:

```python
SKILL_DIRS = (".nanoharness/skills", "skills")
```

Why: a hidden directory for harness-managed skills and a visible one a repository
can commit. First definition of a name wins, so a project can override a shipped
skill.

```python
if text.startswith("---"):
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front) or {}, body.strip()
```

Why: front matter is metadata *about* the skill; the body is instructions *for*
the model. Splitting them is what makes the cheap catalogue possible.

```python
except Exception:
    continue  # a broken skill must not stop the harness from starting
```

Why: skills are user data. A typo in one `SKILL.md` should not prevent the agent
from starting.

```python
return (
    "# Skills\n"
    "These skills hold detailed instructions for specific jobs. If one of them fits the task, "
    "call load_skill with its name and follow what it says before doing anything else.\n"
    + "\n".join(lines)
)
```

Why: the catalogue has to tell the model *when* to load, not just *what* exists.
Descriptions are trigger conditions - write them as "use when ...".

`nanoharness/agent.py`:

```python
self.skills = skills.discover(self.root)
self.system = prompt.system_prompt(self.root, extras=[skills.catalog(self.skills)])
```

Why: the catalogue is stable context, so it belongs in the cached prefix next to
`AGENTS.md`.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> walk me through nanoharness/registry.py the way the code-explainer skill says
you> write tests for nanoharness/skills.py using the test-writer skill
python -m pytest -q test_step.py
```

## What you should see

```text
nanoharness step08 | openrouter | google/gemini-3.5-flash
project: /Users/you/.../step08_skills
skills: code-explainer, test-writer
╭─ load_skill ─────────────────────────────╮
│ {"name": "code-explainer"}               │
╰──────────────────────────────────────────╯
# Skill: code-explainer
(files for this skill live in .../skills/code-explainer)
...
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/skills.py` | new: `discover`, `parse`, `catalog`, and the `load_skill` tool |
| `nanoharness/prompt.py` | `system_prompt` accepts `extras` sections |
| `nanoharness/agent.py` | discovers skills and puts the catalogue in the stable prefix |
| `nanoharness/cli.py` | banner lists the discovered skills |
| `skills/code-explainer/SKILL.md` | new example skill |
| `skills/test-writer/SKILL.md` | new example skill |
| `test_step.py` | rewritten: front matter, both directories, catalogue vs body, load on demand |
| `README.md` | this file |

## Gotchas

- `load_skill` re-reads from disk, so editing a `SKILL.md` takes effect on the
  next call - but the *catalogue* was built at startup, so a brand new skill
  needs a restart.
- Descriptions are the only thing the model uses to choose. "Use when the user
  asks X" beats "a skill for X".
- Requires `pyyaml`. It is in `requirements.txt` at the top of Part A.
