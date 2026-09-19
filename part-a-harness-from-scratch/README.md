# Part A - nanoharness: a coding agent built from scratch, one idea at a time

**nanoharness** is a small coding-agent harness for the terminal: it reads and
writes files, runs shell commands in a sandbox, loads skills, keeps a plan,
remembers sessions, asks before doing anything risky, compacts its own
transcript and delegates to subagents. The finished harness is eighteen small
files, about 1,600 lines of Python including docstrings, on top of the
OpenRouter API.

It is built here fifteen times. Every `stepNN_*/` directory is a **complete,
runnable harness** that adds exactly one idea to the step before it, so

```bash
diff -rq step07_context_injection step08_skills
```

shows only the files that the new idea touched. Each step has a `README.md` with
the code and the reason for it, and a `test_step.py` that runs offline - no API
key, no network - in under a second.

Models are interchangeable. The loop around them is the product; this is what
that loop is made of.

## The fifteen steps

| # | Step | The one new idea | Key files | Try it |
|---|---|---|---|---|
| 01 | `step01_raw_http` | An LLM call is one HTTPS POST: JSON in, JSON out, no hidden state | `raw_call.py` | `python raw_call.py "hello"` |
| 02 | `step02_sdk_chat` | The SDK against OpenRouter (or OpenAI, or Google), and a transcript list that *is* the memory | `nanoharness/llm.py`, `cli.py` | ask two related questions |
| 03 | `step03_first_tool` | A tool is a JSON schema for the model plus a Python function for us | `tools.py` | "how many python files are here?" |
| 04 | `step04_tool_registry` | A `@tool` decorator derives the schema from type hints and the docstring; errors come back as results | `registry.py` | `python -m pytest -q test_step.py` |
| 05 | `step05_agent_loop` | The loop: model -> tools -> model, until text, bounded by `MAX_STEPS` | `agent.py` | "which file here is the longest?" |
| 06 | `step06_edit_tools_ui` | `write_file` / `edit_file` with a strict match contract, and a rich UI | `ui.py`, `tools.py` | "write scratch/calc.py, then fix its bug" |
| 07 | `step07_context_injection` | Stable prefix (`AGENTS.md`) vs a volatile environment block sent late | `prompt.py`, `AGENTS.md` | watch `cached` in the usage line |
| 08 | `step08_skills` | `SKILL.md` files: name and description in the prompt, body behind `load_skill` | `skills.py`, `skills/` | "explain registry.py using the code-explainer skill" |
| 09 | `step09_todos` | A validated plan in harness state, re-injected every call | `todos.py` | "plan, then do: list, count, write the counts" |
| 10 | `step10_sessions` | Append-only JSONL sessions, `--resume`, `/rewind`, and slash commands the model never sees | `session.py`, `commands.py` | `/rewind`, then `--resume` in a new process |
| 11 | `step11_permissions` | allow / ask / deny for commands and writes; strictest segment wins | `permissions.py` | `--read-only`, `--yolo` |
| 12 | `step12_sandbox` | Seatbelt or bubblewrap: read anywhere, write only in the project, no network | `sandbox.py` | "write a file to my home directory" |
| 13 | `step13_compaction` | Trim old tool results; summarise older turns into the system prompt | `compaction.py` | `/compact` |
| 14 | `step14_subagents` | `task()`: a fresh context with read-only tools; only the answer returns | `subagent.py` | "use a subagent to find every policy call site" |
| 15 | `step15_openrouter_routing_cli` | Model fallback, provider routing, a cost ledger, streaming, `pip install -e .` | `llm.py`, `cost.py`, `pyproject.toml` | `/cost`, `/model`, `nanoharness --help` |

## The final loop

```text
          you type a line
                |
        /exit /cost /model ... ----> commands.py           (never sent to the model)
                |
                v
   +------------------------------------------------------------------+
   |  Agent.run()                                       agent.py       |
   |                                                                   |
   |  trim old tool results ------------------------- compaction.py    |
   |  compact if over budget ------------------------ compaction.py    |
   |                                                                   |
   |  request = [ system prompt ] + transcript + [ environment ]       |
   |               ^ prompt.py + skills catalogue        ^ prompt.py   |
   |               ^ + compaction summary                ^ + todos     |
   |                          |                                        |
   |                          v                                        |
   |                     llm.chat() -------------------- llm.py        |
   |            model + fallbacks, provider prefs, streaming           |
   |                          |                                        |
   |            +-------------+--------------+                         |
   |            |                            |                         |
   |       text answer                  tool_calls                     |
   |            |                            |                         |
   |          return            for each call:                         |
   |                             policy.check() ------ permissions.py  |
   |                               allow / ask (you) / deny            |
   |                             registry.run_tool() -- registry.py    |
   |                               bash -> sandbox.wrap  sandbox.py    |
   |                               task -> child Agent   subagent.py   |
   |                             append role=tool result               |
   |                                  |                                |
   |                                  +--> loop again (max MAX_STEPS)  |
   +------------------------------------------------------------------+
                |                                   |
          ui.py renders                    session.py appends
       panels, spinner, cost              every message to JSONL
```

## Setup

```bash
# from the repository root
python3.12 -m venv .venv
.venv/bin/pip install -r part-a-harness-from-scratch/requirements.txt
source .venv/bin/activate

cd part-a-harness-from-scratch
cp .env.example .env          # then put your key in .env (it is gitignored)
```

`.env` is found by searching upward from wherever you run a step, so one file at
the root of Part A covers all fifteen.

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_PROVIDER` | `openrouter` | `openrouter` (default), `openai` or `gemini` |
| `OPENROUTER_API_KEY` | - | required on the openrouter route (`sk-or-...`) |
| `OPENAI_API_KEY` | - | required on the openai route (`sk-proj-...`) |
| `GEMINI_API_KEY` | - | required on the gemini route |
| `HARNESS_MODEL` | per route: `google/gemini-3.5-flash`, `gpt-5-mini`, `gemini-3.5-flash` | model id; it has to match the route |
| `HARNESS_FALLBACK_MODELS` | `deepseek/deepseek-v4-flash` | comma separated; OpenRouter's server-side fallback (step 15) |
| `HARNESS_BASE_URL` | the chosen route's URL | overrides the endpoint for *whichever* route you picked: a gateway, a proxy, a local server |
| `HARNESS_PROVIDER_SORT` | - | `price`, `throughput` or `latency`; OpenRouter only (step 15) |
| `HARNESS_CONTEXT_WINDOW` | `128000` | compaction budget (step 13) |

**The three routes.** `PROVIDERS` in `nanoharness/llm.py` is the whole switch;
nothing else in the harness knows which one is in use.

1. **OpenRouter (default, and what this assignment targets)**: one key for many
   models, `usage.cost` in every response, and server-side model fallback.
2. **OpenAI**: `HARNESS_PROVIDER=openai`, `OPENAI_API_KEY=...`,
   `HARNESS_MODEL=gpt-5-mini` (or `gpt-4.1-mini`). Same code path; OpenAI reports
   tokens but no price, and the `models` / `provider` routing keys are OpenRouter
   extensions, so step 15 does not send them and `/cost` prints `n/a` rather than
   a made-up number.
3. **Gemini**: either bring the key to OpenRouter as BYOK (add it under
   integrations and change nothing here), or go direct with
   `HARNESS_PROVIDER=gemini`, `GEMINI_API_KEY=...`,
   `HARNESS_MODEL=gemini-3.5-flash`. The direct route is the only one that
   rewrites model ids, stripping the `google/` prefix OpenRouter uses.

### Verified live

Run on **2026-09-19** against **OpenAI** (`HARNESS_PROVIDER=openai`,
`HARNESS_MODEL=gpt-5-mini`, no OpenRouter key available at the time), from
scratch directories outside this repository:

| What ran | Result | Usage reported |
|---|---|---|
| step 01, pointed at `https://api.openai.com/v1` | printed request, raw JSON and reply | `usage: prompt=16 completion=114 cached=0 cost=n/a` |
| step 01 again with `gpt-4.1-mini` | replied `ok` | `usage: prompt=12 completion=1 cached=0 cost=n/a` |
| step 06, one turn: "read calc.py and tell me what add() does" | `read_file` then a correct answer that the docstring contradicts the code | `in=549 out=28`, then `in=677 out=526` |
| step 15, full session: todo plan -> `write_file` -> `bash python3 hello.py` (permission prompt, answered `y`) -> `/cost` -> `/model` -> `/sessions` -> `/exit` | streamed the answer, sandbox banner `seatbelt`, 7 model calls | `/cost`: 7 calls, in 9323, cached 0, out 785, `cost n/a` |
| step 15, sandbox probe: "run `echo test > ~/...probe.txt`" | policy asked (redirection), answer `y`, and the kernel still refused: `Operation not permitted`, exit code 1, no file created | `in=1086 out=581` |

Totals for the whole live session: about **12,700 prompt tokens and 2,270
completion tokens on gpt-5-mini**. OpenAI reports no cost, so the harness
correctly prints `n/a`; at the list prices used for this arithmetic ($0.25 per 1M
input, $2.00 per 1M output) that is roughly **$0.008** - check your own dashboard
for the authoritative number.

Nothing needed a code change to make the live runs work. Two things were polished
afterwards because the live output showed them: the "served by ..." note (OpenAI
answers with a dated snapshot id such as `gpt-5-mini-2025-08-07`, which is not a
fallback), and the `/cost` table now fits an 80-column terminal.

## Running a step

```bash
cd step07_context_injection
python -m nanoharness                 # the REPL; /exit to quit
python -m nanoharness --help          # flags available in this step
```

Step 01 is a script: `python raw_call.py "one question"`.
From step 10 on: `--resume`, `--session ID`. From step 11: `--yolo`,
`--read-only`. From step 12: `--no-sandbox`. From step 15: `--model`,
`--no-stream`, `--version`, and `pip install -e .` gives you a `nanoharness`
command that works in any directory.

Demos write into `scratch/`, which is gitignored, so the step directories stay
clean for `diff -rq`.

## Running the tests

```bash
python run_tests.py            # all fifteen, a pass/fail table
python run_tests.py 11-15      # a range
python run_tests.py 5          # one step
cd step05_agent_loop && python -m pytest -q test_step.py    # the raw output
```

Every test scripts a fake model (`FakeLLM`) and asserts on what the harness did
with it: the order of `role="tool"` messages, that a slash command never reached
the model, that the environment block is not in the transcript, that a denied
command never ran. `run_tests.py` strips `OPENROUTER_API_KEY` from the
environment before running them, so a test that secretly needs the network fails
instead of passing quietly.

Each step runs in its own subprocess, because all fifteen contain a package
called `nanoharness` and only one of them can be imported per process.

## Concepts

**The prefix rule.** Providers cache long, identical prompt prefixes and charge
less for a hit. So: never change the beginning of the request. The system prompt
is built once at startup (step 07); the transcript only ever grows at the end;
anything volatile - the clock, the git branch, the current plan - is appended to
the *request* as the last message and is never stored (steps 07 and 09). The two
places that break this on purpose - trimming and compaction (step 13) - do it at
most once per turn and tell you why.

**Errors as results.** A tool that raises ends the turn; a tool that returns
`"Error: ..."` gives the model another move. `run_tool` catches bad JSON, unknown
tools, wrong arguments and exceptions (step 04). Permission verdicts go back the
same way (step 11), as do interrupted tool calls in a resumed session (step 10).
The rule: anything the model could react to should reach it as text.

**Late injection.** Facts that change belong at the end of the request, in one
current copy, not scattered through the history. The environment block, the todo
list, and a resumed session's repairs are all late-injected. It keeps the prefix
cacheable *and* stops the model acting on a plan it wrote six tool calls ago.

**Permission vs sandbox.** The permission engine reads the command text and
decides whether to ask you; it is UX and policy, and a clever command line can
fool it. The sandbox is the kernel refusing to open the file; it is enforcement,
and it does not care how clever the command was. You want both: policy alone is
theatre, and a sandbox alone asks you nothing before deleting your work inside
the project.

**Compaction vs subagents.** Compaction is what you do once the context is
already full: summarise the past and lose detail. A subagent avoids filling it:
thirty tool calls happen in a context you throw away, and one paragraph comes
back. Reach for a subagent before a big exploration, for compaction after a long
session. Both cost a model call; neither is free.

## Credits

The step-by-step shape of this course was inspired by two public projects, read
for their sequence of ideas and then set aside - all code and prose here is our
own:

- [dlmastery/simple-coding-harness](https://github.com/dlmastery/simple-coding-harness) - "zero to hero: harness engineering", one idea per stage.
- [avbiswas/neural-code](https://github.com/avbiswas/neural-code) - a minimal coding agent from the Neural Breakdown video.

Part B of this repository runs the same ideas on the DeepSeek Harness with
plugins; Part C builds an autoresearch harness on top of the same loop.
