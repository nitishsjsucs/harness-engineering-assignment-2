# Research program: quickstart (spiral classification)

You are running an autoresearch loop. Your job is to lower `val_loss` (mean
cross-entropy on the validation split) by editing `train.py`, one idea at a time.

## Files

| file | role |
|---|---|
| `train.py` | **editable** -- features, model, optimiser, training loop |
| `prepare.py` | **frozen** -- dataset, splits, the loss, the METRIC line, `TIME_BUDGET` |
| `autoresearch.toml` | **frozen** -- the rules of this task |

The harness refuses edits to anything but `train.py`, so there is no point
trying. `prepare.TIME_BUDGET` (3 seconds of training) is frozen too: buy better
scores with better ideas, not with more compute.

## The loop

1. Read the ledger (`arh status`, or the `show_history` tool) before you think.
   Do not retry an idea that already failed, and do not undo a kept improvement.
2. Form one hypothesis. Write it down as the experiment description: what you
   changed, and what you expect it to do.
3. Make ONE focused change to `train.py`.
4. Evaluate it: `arh run -m "<description>"` (or the `run_experiment` tool).
5. Read the verdict. `keep` means the change is committed and is now the
   baseline for the next idea. `discard`, `crash` and `invalid` mean your edit
   has already been reverted -- the file on disk is the last kept version again.
6. Go back to 1. Do not ask whether to continue; continue.

## What usually helps here

A linear model cannot separate spirals, so the first large win is a non-linear
model. After that: hidden width, activation, learning rate and schedule,
initialisation, better input features, a second layer, mini-batching, momentum
or Adam, regularisation. Time is the binding constraint -- a bigger model runs
fewer steps in the same 3 seconds, and that trade-off is the interesting part.

## Rules

- Never print a `METRIC` line yourself. `prepare.report()` owns the score.
- Never read the val or holdout split. Training data comes from
  `prepare.training_data()`.
- Prefer the simpler version. A 0.001 gain that costs thirty lines of special
  cases is not worth it; the same gain from deleting code always is.
- One change per experiment. Two changes in one run teach you nothing about
  either.
- A crash is information. Log it and move on unless the fix is trivial
  (a typo, a missing import).
