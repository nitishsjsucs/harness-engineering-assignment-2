# `tests/`

109 tests, no network, no API key, no torch, under a minute.

```bash
pip install -e ".[dev]"
pytest part-c-autoresearch-harness/tests -q
```

A harness whose guards are untested is a harness with opinions, not
guarantees. Every guard in the README's diagram has a test that makes it fire.

| file | what it pins down |
|---|---|
| `conftest.py` | the toy task: `train.py` holds `VALUE = 5.0`, the frozen `prepare.py` scores `|VALUE - 3|`. Same shape as a real task, milliseconds per run |
| `test_spec.py` | the spec loads, rejects contradictions (a file both editable and frozen, a missing file, a bad direction), and the path-matching rules |
| `test_runner.py` | metric parsing, exit codes, stale `metrics.json`, unsetting an env var -- and that a timeout kills a **grandchild** process, not just the shell |
| `test_engine.py` | keep / discard / crash / timeout / invalid, reverts, every guard (frozen edit, runtime tampering, forbidden pattern, bounds, duplicate metric, `GUARD_FAIL`, new files, holdout rejection), the lock, and the refusal to run after a hand-made commit |
| `test_gitops.py` | isolated mode leaves an enclosing repository untouched; repo mode branches inside it and commits only task paths; a discard does not revert the human's unrelated work |
| `test_ledger_and_report.py` | TSV shape, tabs in a description cannot break the grid, append-only enforcement, consistency checking, and that the report really writes a PNG |
| `test_agent.py` | the agent's tools refuse frozen paths and escapes, a repeated `read_file` is answered with an instruction instead of the file, the episode loop runs one experiment per episode and stops at both the experiment budget and the request cap, and the chat-model plumbing for each provider (OpenRouter's fallback models and its real `0.0` for a free model, OpenAI's absent price) with a fake client |
| `test_hooks.py` | the Claude Code hooks, run the way Claude Code runs them (JSON on stdin): frozen file blocked, editable allowed, ledger blocked, malformed input fails closed -- plus a parity test that the hook's copy of the matching rules agrees with the engine's |
| `test_tasks.py` | the shipped specs load, the quickstart evaluator refuses malformed output, and the demo script is well formed |

Three tests deserve a look during a walkthrough:

**`test_a_run_that_rewrites_the_evaluator_is_caught_after_the_fact`** -- the
training script appends to `prepare.py` while it runs. The pre-run hash check
cannot see that; the post-run one does, and the file is restored.

**`test_tampering_during_the_holdout_run_is_still_caught`** -- the holdout
confirmation run rewrites `prepare.py` after every earlier check has passed.
The last look before the commit catches it and the keep becomes `invalid`.

**`test_timeout_kills_the_whole_process_group`** -- the run spawns a child that
sleeps for a minute. After the budget expires, the test waits for that
*grandchild* pid to disappear. Killing only the shell would leave it burning
the next experiment's compute.
