# `tasks/` -- what the loop works on

A task is a directory with four things:

| file | role |
|---|---|
| `autoresearch.toml` | the contract: editable files, frozen files, run command, budget, metric, guards |
| `prepare.py` | **frozen**: data preparation and the evaluator. It owns the score and prints the only `METRIC` line |
| `train.py` | **editable**: the only file an experiment may change |
| `program.md` | the research direction, used as the system prompt for the proposer |

Two tasks ship here:

| task | needs | per experiment | metric | baseline |
|---|---|---|---|---|
| [`quickstart/`](quickstart/) | numpy | ~4 s (CPU) | `val_loss`, cross-entropy on spirals | 0.9605 |
| [`tinygpt/`](tinygpt/) | torch (MPS/CUDA/CPU) | ~61 s | `val_bpb`, bits per byte on tiny-shakespeare | 2.50009 |

Use `quickstart` to demo or test the loop end to end in a couple of minutes;
use `tinygpt` for a real overnight run.

## Always work on a copy

`arh init` writes state into the task directory and modifies `train.py` as
experiments run. Copy the task somewhere else first, so the shipped version
stays as the starting line:

```bash
cp -r tasks/quickstart /tmp/qs && cd /tmp/qs && arh init . && arh baseline
```

## Writing your own task

1. Put **everything that defines the score** in the frozen file: the data, the
   splits, the loss, the sanity checks on the model's output, and the `print`
   of the `METRIC` line. If the editable file can print the score, the score is
   not a measurement.
2. Make the budget part of the frozen file (`TIME_BUDGET`), and set
   `[run].budget_seconds` above it as a hard kill.
3. Give the evaluator two failure modes: `GUARD_FAIL <reason>` when the model
   breaks a rule (wrong shape, not causal, not a distribution) and a non-zero
   exit when the run simply diverged. The harness records the first as
   `invalid` and the second as `crash`, which are very different things to a
   human reading the ledger.
4. Set `[guards].bounds` to the range a real result can fall in, and
   `forbid_patterns` to the identifiers that only cheating code would mention.
5. Write `program.md` as if for a new colleague who will never ask a follow-up
   question, because the proposer will not.
