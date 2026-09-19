# A live run on the free default -- and what it did not produce

2026-09-19, provider `openrouter`, model `deepseek/deepseek-v4-flash-0731:free`
(the harness's documented default), same task and same commands as the
`gpt-5-mini` run next door.

```bash
HARNESS_PROVIDER=openrouter arh init . --tag orfree && arh baseline
arh loop --agent openrouter --max 3 --max-requests 8    # attempt 1
arh loop --agent openrouter --max 1 --max-requests 2    # attempt 2, after a fix
```

**Result: zero experiments in 10 API requests.** The ledger here contains the
baseline and nothing else, and that is the honest artefact.

| attempt | requests | tokens | cost | what the model did | experiments |
|---|---|---|---|---|---|
| 1 | 8 (cap) | 57,121 | $0.0000 | ten `read_file` calls -- `prepare.py` six times, `autoresearch.toml` twice, one for a path it invented (`@prepare.py`) | 0 |
| 2 | 2 (cap) | 8,344 | $0.0000 | read `train.py`, `prepare.py`, `autoresearch.toml`, then `show_history` | 0 |

Full transcripts: [`loop-attempt-1.log`](loop-attempt-1.log),
[`loop-attempt-2.log`](loop-attempt-2.log).

## What this proves, and what it does not

**The OpenRouter path works.** Authentication, tool schemas, tool calls coming
back, usage accounting, the request cap, the clean stop and the ledger were all
exercised end to end against the real API. `cost $0.0000` is a *reported* zero
from a free model -- the harness prints that, and prints `n/a` when a provider
reports no price at all, because those are different facts.

**The proposer did not work.** The model never called `edit_file`, so the loop
never had anything to measure. No hypothesis, no diff, no row.

**The harness behaved exactly as it should.** It did not invent progress, it
did not record an experiment that never ran, and the request cap stopped an
unproductive loop instead of quietly draining a daily quota:

```
[arh] stopped: request cap reached (8). 0 experiments, 0 kept. 8 requests, 57121 tokens, cost $0.0000
```

An empty ledger after 57k tokens is information. The same harness, same task
and same prompt with `gpt-5-mini` produced six experiments and four keeps (see
[`../quickstart-live-gpt5mini/`](../quickstart-live-gpt5mini/)). **The proposer
is a swappable component, and the difference in proposer quality is visible in
the ledger rather than hidden in a transcript** -- which is the entire argument
for keeping the measurement outside the model.

## The fix this run produced

Attempt 1 re-read `prepare.py` six times. On a metered API every repeat is a
paid request that cannot produce an experiment, so `TaskTools.dispatch` now
answers a repeated `read_file` within one episode with an instruction instead
of the file:

```
ALREADY READ: prepare.py is unchanged since you read it in this episode.
Stop reading and act: make ONE change to an editable file with edit_file,
then call run_experiment.
```

Covered by `tests/test_agent.py::test_read_any_file_in_the_task`. Be careful
what you read into attempt 2, though: its three reads were of *different*
files, so the new guard never fired there. It is a fix for the pathology seen
in attempt 1, not a fix that has been shown to rescue this model -- the daily
free-tier quota (10 requests was the whole budget for this experiment) ran out
before it could be tested properly.
