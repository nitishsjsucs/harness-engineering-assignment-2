# Harness Engineering — Assignment 2

Three harnesses, built and demonstrated:

| Part | What it is | Folder |
|---|---|---|
| **A** | A coding-agent harness written from scratch, one idea per step, on the **OpenRouter** API | [`part-a-harness-from-scratch/`](part-a-harness-from-scratch) |
| **B** | **DeepSeek Harness** customised in Creator mode: 7 community plugins, 2 plugins written from scratch, 2 domain presets | [`part-b-deepseek-harness/`](part-b-deepseek-harness) |
| **C** | A custom **ML autoresearch harness**, shipped as a plugin for a coding assistant | [`part-c-autoresearch-harness/`](part-c-autoresearch-harness) |

Author: **nitishsjsucs** · SJSU · September 2026

---

## The one idea

A model is a function from a list of messages to one message. Everything that makes it feel like a
colleague — tools, memory, a plan, permission to act, a sandbox, a way to stop — lives in the loop
*around* the model. That loop is the harness, and it is the part you can actually engineer.

These three parts attack it from three directions:

- **Part A builds the loop by hand** so nothing about it is magic: 15 steps from one HTTP POST to a
  harness with tools, skills, sessions, permissions, a kernel sandbox, compaction, subagents and cost
  routing.
- **Part B takes a production harness apart** — DeepSeek's `dsh`, where *everything is a plugin* — and
  extends it: installed plugins, plugins written from scratch, and domain agents built as presets.
- **Part C points a harness at research instead of code**: an autoresearch loop that edits one file,
  measures, and keeps or reverts — with the guards that stop an agent from cheating the metric.

---

## Part A — a harness from scratch, on OpenRouter

[`part-a-harness-from-scratch/`](part-a-harness-from-scratch) · Python 3.10+ · OpenRouter (Gemini, DeepSeek,
or any OpenAI-compatible backend)

Fifteen runnable steps. Each is the previous one plus exactly one idea, so `diff -r stepNN stepNN+1`
shows that idea and nothing else. Every step has a README explaining the code and an offline test that
runs without an API key.

```
step01_raw_http          one POST, the JSON, the usage and cost line
step02_sdk_chat          the SDK client, the transcript as memory
step03_first_tool        a schema for the model, a function for us
step04_tool_registry     @tool decorator: schema derived from type hints
step05_agent_loop        call -> tool calls -> results -> repeat
step06_edit_tools_ui     write/edit files, a readable terminal
step07_context_injection stable prefix, volatile facts appended per request
step08_skills            index in the prompt, body on demand
step09_todos             a plan that survives twenty tool calls
step10_sessions          append-only JSONL, resume, rewind
step11_permissions       allow / ask / deny before a command runs
step12_sandbox           the kernel enforces it, not the rules
step13_compaction        keep a long conversation inside the window
step14_subagents         spend context somewhere disposable
step15_openrouter_routing_cli   fallbacks, cost ledger, streaming, installable CLI
```

Run the tests for all of them: `python run_tests.py`.

### How the loop actually works

The finished harness is 18 files, ~1,650 lines, in
[`step15_openrouter_routing_cli/nanoharness/`](part-a-harness-from-scratch/step15_openrouter_routing_cli/nanoharness).
Four mechanisms carry it.

**The turn loop** — [`agent.py:88`](part-a-harness-from-scratch/step15_openrouter_routing_cli/nanoharness/agent.py).
One user turn runs to completion inside a **bounded** `for _ in range(MAX_STEPS)`, not a
`while True`; `MAX_STEPS = 25`, because "a confused model must not burn the account".
Each pass compacts if over budget, calls the model, records usage, appends the reply,
and then branches on one thing: if the reply carries no `tool_calls`, its text is the
answer and the loop returns. Otherwise it runs the calls and goes round again.

**The transcript** has exactly one append path, `Agent.add()`, so the session log cannot
drift from memory. The system prompt is *not* stored in it, and neither is the
`<environment>` block (cwd, git branch, timestamp, todos) — that is appended to each
request and thrown away, which keeps the cacheable prefix stable. On a live OpenRouter
run this showed up as 8,563 of 9,228 prompt tokens served from cache across five calls.

**Tool registration is a dict and a decorator** —
[`registry.py`](part-a-harness-from-scratch/step15_openrouter_routing_cli/nanoharness/registry.py).
`@tool` puts `{name: {fn, schema}}` into a module-level `TOOLS` dict at import time. The
JSON Schema is **derived from type hints**, never hand-written: `Literal` becomes an
enum, `TypedDict` becomes a nested object, a parameter without a default becomes
required, and the Google-style docstring becomes the description the model reads. A
parameter named `agent` is harness state — hidden from the schema and stripped from the
arguments, so a model that guesses the name still cannot set it.

**Dispatch never raises.** `run_tool()` turns every failure — unknown tool, malformed
JSON, wrong signature, a buggy tool body — into a string result the model can read and
recover from. Between the loop and the registry sits `gated_run()`, which applies the
permission policy (allow / ask / deny) and returns an explanatory refusal rather than
throwing.

The eight tools: `bash`, `read_file`, `list_dir`, `write_file`, `edit_file`,
`load_skill`, `write_todos`, `task`. The last one spawns a subagent with an empty
context and a deliberately reduced toolset — `("bash", "read_file", "list_dir",
"load_skill")`, no write tools and no `task`, so it cannot recurse or mutate — and
returns only its final answer.

Two notes on limits, both found by testing rather than assumed: there is **no
client-side retry** anywhere in Part A (failover is delegated to OpenRouter's server-side
`models` chain), and that chain is not consulted when the primary model id is simply
invalid — the API returns 400 first.

## Part B — DeepSeek Harness in Creator mode

[`part-b-deepseek-harness/`](part-b-deepseek-harness) · `@deepseek-ai/dsh@0.1.5-rc.2`

- **Seven community plugins**, each covering a different extension point: a plugin market, a tool the
  agent uses to find more plugins, a sidebar workbench, a context dashboard, keyless web search,
  conversation navigation, and a theme. See [community-plugins.md](part-b-deepseek-harness/community-plugins.md).
- **Two plugins written from scratch**:
  - [`dsh-second-brain`](part-b-deepseek-harness/plugins/dsh-second-brain) — five tools over an
    Obsidian-compatible Markdown vault (capture, BM25 search, read-with-backlinks, list, link), a
    system-prompt section, a loopback-only JSON API and a floating panel in the Web UI. Memory that
    outlives the session.
  - [`dsh-dino-break`](part-b-deepseek-harness/plugins/dsh-dino-break) — a T-rex runner floating in the
    corner, built from one sentence in Creator mode. Zero Host code; the shortest tour of the Client half.
- **Two domain agents as presets, not forks**: an *ML Researcher* (experiment discipline, no unattended
  loops) and a *Research Librarian* (no shell, no file writes — a capability boundary, not a polite persona).
- The Creator-mode prompts, what the agent inspects for each, and the corrections that turn a demo into a
  plugin: [creator-mode-prompts.md](part-b-deepseek-harness/creator-mode-prompts.md).

## Part C — an ML autoresearch harness

[`part-c-autoresearch-harness/`](part-c-autoresearch-harness) · Python · a plugin for a coding assistant

Karpathy's autoresearch loop — edit one file, run under a fixed time budget, keep the change if the metric
improved, revert if it did not, repeat — rebuilt as a harness with the parts that decide whether the loop
produces knowledge or noise: an append-only experiment ledger, frozen evaluation files whose hashes are
checked on every run, an editable-file allowlist enforced on the git diff, and a holdout check before a new
best is accepted. It runs end to end from a coding assistant (a Claude Code plugin with commands, a skill,
a reviewer subagent and a fail-closed PreToolUse hook) or headless with no assistant at all.

### The recorded runs

Three run directories are committed under
[`examples/`](part-c-autoresearch-harness/examples), each with the machine-written
`results.tsv`, `experiments.jsonl`, per-experiment `.log` and `.diff`, and a generated
`report.md`. Nothing in them is transcribed by hand.

| Run | Proposer | Baseline → best | Experiments | Requests / tokens / cost |
|---|---|---|---|---|
| [`quickstart-live-gpt5mini`](part-c-autoresearch-harness/examples/quickstart-live-gpt5mini) | gpt-5-mini, unattended | 0.960452 → **0.005833** (−99.4%) in 3 m 16 s | 6: 4 kept, 2 discarded | — / 49,062 / `n/a` |
| [`quickstart-run`](part-c-autoresearch-harness/examples/quickstart-run) | scripted hypotheses | 0.960452 → **0.009255** (−99.0%) | 8: 4 kept, 2 discarded, 1 crash, **1 invalid** | — |
| [`quickstart-live-openrouter-free`](part-c-autoresearch-harness/examples/quickstart-live-openrouter-free) | free-tier model, unattended | 0.960452 → **nothing** | **0** | 10 / 65,465 / $0.0000 |

Three things in that table are the actual argument for building a harness:

**The invalid row cost 0.00 s.** `quickstart-run` experiment 6 proposed training on the
validation split. The diff was scanned before any compute, matched a forbidden pattern,
and was rejected — `duration_s` is `0.000000` and there is no `0006.log`, because no
process ever started. The diff is committed so you can read the hack.

**A correct change was reverted on the measurement.** In the gpt-5-mini run, experiment 2
was a properly implemented Adam optimiser. It scored 0.872086 against a best of 0.872082
— four millionths worse — and was reverted in about three seconds. No argument, a
measurement.

**The empty run is kept deliberately.** The free model read `prepare.py` six times,
proposed no edit, and hit the request cap at 57k tokens. That result is in the repository
because a harness that cannot invent progress reports none, and because it makes the
proposer visibly a swappable component. It also drove a fix: a repeated identical
`read_file` inside one episode now returns an instruction instead of the file.

Note the cost column distinguishes `n/a` from `$0.0000` throughout: the OpenAI API
reports no price field, while the free OpenRouter model reports an actual zero. The code
treats "the provider told us nothing" and "the provider told us it was free" as different
facts rather than summing both as zero.

Detail on each:

- **[`quickstart-run`](part-c-autoresearch-harness/examples/quickstart-run)** — `val_loss` 0.960 -> 0.0093
  over eight experiments: four kept, one discarded, one crashed on NaN, and one **rejected in 0.00 s
  before any compute**, because the proposed diff reached into the validation split. That row is the
  entire argument for building a harness instead of writing a prompt.
- **[`quickstart-live-gpt5mini`](part-c-autoresearch-harness/examples/quickstart-live-gpt5mini)** — the
  same task driven autonomously by a model, no human in the loop after the first command:
  **0.960452 -> 0.005833, −99.4% in 3 min 16 s**, four kept and two reverted. The instructive one is
  experiment 2: the model wrote a correct Adam optimiser and the harness measured it four *millionths*
  worse than plain SGD, then reverted it in three seconds. No argument, a measurement.
- **[`quickstart-live-openrouter-free`](part-c-autoresearch-harness/examples/quickstart-live-openrouter-free)** —
  the same harness, same task, same prompt, on a free model: **zero experiments**. It read `prepare.py`
  six times and never proposed an edit, and the request cap stopped it at 57k tokens. Kept exactly as it
  happened, because it is the most useful result in the folder: the proposer is a swappable component,
  the difference between models is visible in the ledger, and a harness that cannot invent progress
  reports none.

The `tinygpt` task is the real thing: a 4-layer character GPT on tiny-shakespeare, 60-second budget on
Apple Silicon (MPS), baseline `val_bpb 2.50`. Two runs of identical code differ by ~0.026 bpb, which is
why the harness has a `min_delta` and why the docs call a single-run improvement provisional.

---

## Running everything

```bash
git clone https://github.com/nitishsjsucs/harness-engineering-assignment-2
cd harness-engineering-assignment-2

# Part A
python3.12 -m venv .venv && .venv/bin/pip install -r part-a-harness-from-scratch/requirements.txt
cp part-a-harness-from-scratch/.env.example part-a-harness-from-scratch/.env   # add OPENROUTER_API_KEY
.venv/bin/python part-a-harness-from-scratch/run_tests.py                      # offline, no key needed

# Part B
npm install -g @deepseek-ai/dsh
cd part-b-deepseek-harness && ./scripts/install-community-plugins.sh web && ./scripts/install-local-plugins.sh web && ./scripts/install-presets.sh

# Part C
.venv/bin/pip install -e part-c-autoresearch-harness
.venv/bin/python -m pytest part-c-autoresearch-harness/tests -q
```

No API key is needed to run any of the test suites: they drive scripted fake models. A key is needed only
to talk to a real one — and the defaults everywhere are **free-tier OpenRouter models**
(`deepseek/deepseek-v4-flash-0731:free`, falling back to `nvidia/nemotron-3.5-lightning:free`), so the
whole repository can be run end to end at zero cost. A Part A test asserts that nothing in the default
configuration can spend money. Paid models are a one-line swap via `HARNESS_MODEL`.

OpenRouter's free tier allows 20 requests per minute and 50 per day (1000 once an account has bought
$10 of credit). One agent turn is five or six requests, so budget accordingly.

**Verified from a clean clone on 2026-09-20** (macOS 26, arm64, Python 3.12, Node 25):
Part A **15/15 steps, 165 tests**; Part B **9 vault tests**; Part C **109 tests** — 283 in
total, all offline against scripted fake models. With a real key, live runs of all three
(details in each part's README). There is no CI: every figure here is a local run, and the
three commands above reproduce it.

## Credits

The ideas are not mine; the code is. Built while reading
[dlmastery/simple-coding-harness](https://github.com/dlmastery/simple-coding-harness),
[avbiswas/neural-code](https://github.com/avbiswas/neural-code),
the [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) documentation and its
[awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) ecosystem,
[karpathy/autoresearch](https://github.com/karpathy/autoresearch) and
[WecoAI/awesome-autoresearch](https://github.com/WecoAI/awesome-autoresearch).

## License

MIT, except where a directory states otherwise.
