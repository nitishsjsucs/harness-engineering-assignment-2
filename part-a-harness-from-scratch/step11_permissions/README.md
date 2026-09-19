# Step 11: permissions

**Goal:** stop asking the user about `ls`, and never stop asking about `rm -rf`.

**The idea:** a policy engine in front of `run_tool` that returns one of three
verdicts - allow, ask, deny - and reports whatever happens back to the model as a
tool result. Compound commands are split and the strictest segment wins; anything
we cannot read with confidence becomes "ask". Two flags change the whole posture:
`--yolo` (allow all but the deny list) and `--read-only` (refuse everything that
is not on the read-only allow list).

This is *policy*: it reasons about the text of a command. Step 12 adds the
kernel-level *enforcement* underneath it.

## The code

`nanoharness/permissions.py`:

```python
lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
lexer.whitespace_split = True
```

Why: `ls && rm -rf build` is two commands, and so is `ls\nrm -rf build`. A policy
that only looks at the first word of the string is trivially bypassed by a
newline, so the string is tokenised and split on real separators.

```python
def strictest(left: Verdict, right: Verdict) -> Verdict:
    return right if _STRICTNESS[right.decision] > _STRICTNESS[left.decision] else left
```

Why: one rule for combining verdicts. `git status && rm -rf x` is as dangerous as
its worst part.

```python
if uses_substitution(command):
    verdict = strictest(verdict, Verdict(ASK, "it uses command substitution, so the real command is hidden"))
```

Why: `echo $(rm -rf /tmp/x)` looks like an `echo`. If we cannot see what runs, a
human should.

```python
target = redirect_target(tokens)
if target is not None:
    return Verdict(ASK, f"it redirects output into {target}")
```

Why: `cat a.txt` reads, but `cat a.txt > b.txt` writes. The allow list is about
verbs; redirection changes what the verb does. `2>/dev/null` and fd copies are
exempt, since they write nothing.

```python
if ".git" in target.parts:
    return Verdict(DENY, "files inside a .git directory are never written by the agent")
```

Why: a corrupted object store loses work in a way no undo can fix. Deny, in every
mode, including `--yolo`.

`nanoharness/agent.py`:

```python
if verdict.decision == permissions.DENY:
    self.ui.error(f"denied: {verdict.reason}")
    return (
        f"Permission denied: {verdict.reason}. Do not try this again; "
        "tell the user what you wanted to do and why."
    )
```

Why: errors as results, again. The model is told *why* it was refused and what to
do instead, so the turn continues instead of dying.

```python
if answer == "a":
    remembered = self.policy.remember(name, raw_arguments)
```

Why: "always" records the verb (`bash:pytest`), not the exact string, so the
second `pytest -x` does not interrupt the user again. It lasts for the session
only - nothing is written to disk.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness                 # asks before anything that writes
python -m nanoharness --read-only     # a safe mode for exploring a strange repo
python -m nanoharness --yolo          # for a scratch directory you do not care about
python -m pytest -q test_step.py
```

Try: `you> delete every .pyc file under this directory` and answer `n`.

## What you should see

```text
╭─ permission needed: bash ────────────────────────────────────────╮
│ $ find . -name '*.pyc' -delete                                   │
│                                                                  │
│ why you are being asked: 'find' with -delete can change files    │
╰──────────────────────────────────────────────────────────────────╯
allow? [y]es / [N]o / [a]lways for this session: n
```

and the model receives `The user declined this tool call. ...`

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/permissions.py` | new: `Verdict`, `Policy`, command splitting, allow/deny lists, path rules |
| `nanoharness/agent.py` | `gated_run` checks the policy before every call; takes `policy` and `approve` |
| `nanoharness/ui.py` | `confirm()` approval panel |
| `nanoharness/cli.py` | `--yolo` / `--read-only`, mode in the banner |
| `test_step.py` | rewritten: 15 command cases, path rules, modes, the three gate outcomes |
| `README.md` | this file |

## Gotchas

- The allow list is a convenience, not a security boundary. `python -c "..."` is
  asked about because we cannot read what it does; `awk` and `sed` are left off
  the list because both can write files.
- When stdin is not a terminal, `confirm()` answers "no" instead of blocking.
- `--yolo` still refuses the deny list and `.git`. There is no mode that allows
  `sudo`.
