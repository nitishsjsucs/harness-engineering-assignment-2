# Step 12: a sandbox under the permissions

**Goal:** make "it cannot write there" true at the kernel level, not just in our
rule table. And stop one `find /` from eating the context window.

**The idea:** every shell command is wrapped in a kernel sandbox - Seatbelt
(`sandbox-exec`) on macOS, bubblewrap on Linux - that allows reading anywhere,
writing only inside the project directory and the temp directory, and no network
at all. If neither is available we say `sandbox: none` in the banner instead of
pretending. Output is capped at 20k characters, with the full text spilled to a
file the agent can read if it really needs it.

**Permission vs sandbox**: permissions decide *whether to ask you*; the sandbox
decides *what is possible*. The permission engine can be fooled by a clever
command line. The kernel cannot.

## The code

`nanoharness/sandbox.py`:

```python
SEATBELT_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write*
    (subpath (param "PROJECT"))
    (subpath (param "TMPDIR"))
    ...
```

Why: start from "everything allowed", then subtract the two things that cause
real damage - writes outside the project and network access. A deny-by-default
profile is safer in theory and unusable in practice (every compiler needs a
hundred paths).

```python
"-D", f"PROJECT={project}",
```

Why: the project path arrives as a *parameter*, never spliced into the profile
text. Our own repository path contains spaces and brackets; string interpolation
into a policy language is how sandboxes get escaped.

```python
project = os.path.realpath(str(root))  # /tmp is a symlink on macOS; the profile needs the real path
```

Why: on macOS `/tmp` is `/private/tmp`, and Seatbelt matches the real path. This
one line is the difference between a working sandbox and a confusing "Operation
not permitted".

```python
"--ro-bind", "/", "/",  # everything readable...
"--bind", project, project,  # ...but only the project writable
"--unshare-net",  # no network namespace: no network
```

Why: bubblewrap builds the view of the filesystem in order, so the writable bind
must come after the read-only root.

`nanoharness/tools.py`:

```python
head, tail = text[: limit // 2], text[-limit // 4 :]
...
cut = len(text) - len(head) - len(tail)
return (
    f"{head}\n\n[... {cut} characters cut out of {len(text)}. The full output is in {spill} - "
    f"read it with read_file, or narrow it down with grep ...]\n\n{tail}"
)
```

Why: the head shows what the command was doing, the tail shows how it ended
(stack traces and exit codes live there), and the spill file means nothing is
actually lost.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> try to write a file to my home directory, then tell me what happened
you> can you curl example.com?
python -m nanoharness --no-sandbox     # opt out, e.g. when you need network in a tool
python -m pytest -q test_step.py
```

## What you should see

```text
sandbox: seatbelt (write only inside the project, no network)
...
bash: /Users/you/oops.txt: Operation not permitted
[exit code 1]
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/sandbox.py` | new: `detect`, `wrap` (Seatbelt / bubblewrap / none), `describe` |
| `nanoharness/tools.py` | `bash` takes the injected `agent`, runs through `sandbox.wrap`, output goes through `cap_output` |
| `nanoharness/agent.py` | picks a sandbox at startup and exposes it as `agent.sandbox` |
| `nanoharness/cli.py` | `--no-sandbox` flag, sandbox line in the banner |
| `test_step.py` | rewritten: argv shapes, a real Seatbelt write/network test, capping and spill files |
| `README.md` | this file |

## Gotchas

- `sandbox-exec` is deprecated by Apple but has worked for a decade and is what
  most shipping harnesses still use. If it disappears, `detect()` returns
  `none` and the banner tells the truth.
- The sandbox covers `bash` only. `write_file` and `edit_file` are Python calls
  inside our own process, so their protection is the permission engine.
- No network means no `pip install` inside the agent. That is usually what you
  want; `--no-sandbox` is the escape hatch.
- Spill files land in the system temp directory and are not cleaned up
  automatically - the agent may still want to read them later in the session.
