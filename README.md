# Harness Engineering — Assignment 2

Three harnesses, built and demonstrated:

| Part | What it is | Folder | Video |
|---|---|---|---|
| **A** | A coding-agent harness written from scratch, one idea per step, on the **OpenRouter** API | [`part-a-harness-from-scratch/`](part-a-harness-from-scratch) | _(link)_ |
| **B** | **DeepSeek Harness** customised in Creator mode: 7 community plugins, 2 plugins written from scratch, 2 domain presets | [`part-b-deepseek-harness/`](part-b-deepseek-harness) | _(link)_ |
| **C** | A custom **ML autoresearch harness**, shipped as a plugin for a coding assistant | [`part-c-autoresearch-harness/`](part-c-autoresearch-harness) | _(link)_ |

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

Two recorded runs are in [`examples/`](part-c-autoresearch-harness/examples):

- **[`quickstart-run`](part-c-autoresearch-harness/examples/quickstart-run)** — `val_loss` 0.960 -> 0.0093
  over eight experiments: four kept, one discarded, one crashed on NaN, and one **rejected in 0.00 s
  before any compute**, because the proposed diff reached into the validation split. That row is the
  entire argument for building a harness instead of writing a prompt.
- **[`quickstart-live-gpt5mini`](part-c-autoresearch-harness/examples/quickstart-live-gpt5mini)** — the
  same task driven autonomously by a model, no human in the loop after the first command:
  **0.960452 -> 0.005833, −99.4% in 3 min 16 s**, four kept and two reverted. The instructive one is
  experiment 2: the model wrote a correct Adam optimiser and the harness measured it four *millionths*
  worse than plain SGD, then reverted it in three seconds. No argument, a measurement.

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
to talk to a real one.

**Verified from a clean clone on 2026-09-19** (macOS 26, arm64, Python 3.12, Node 25):
Part A 15/15 steps (135 tests), Part B 9 vault tests, Part C 108 tests — and, with a real key,
live runs of all three (details in each part's README).

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
