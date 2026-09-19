# `quickstart` -- the four-second task

Three interleaved spirals, 3600 points, 3 classes. The baseline is multinomial
logistic regression, which cannot bend around a spiral, so the first real idea
wins a lot. One experiment takes about four seconds, which makes this the task
to use for demos, tests and any change to the harness itself.

```bash
cp -r tasks/quickstart /tmp/qs && cd /tmp/qs
arh init . --tag demo
arh baseline          # METRIC val_loss=0.960452  (about 3.1 s)
```

## The measurement

`prepare.py` is frozen and owns everything that defines the score:

```python
def evaluate(predict_proba):
    split = "holdout" if os.environ.get("ARH_EVAL_SPLIT") == "holdout" else "val"
    X, y = _split(split)
    probs = np.asarray(predict_proba(X), dtype=np.float64)
    ...
    if probs.min() < 0 or not np.allclose(probs.sum(axis=1), 1.0, atol=1e-3):
        raise ValueError("predict_proba must return rows that are non-negative and sum to 1")
```

Three things to notice:

1. The model is handed **features only**. It never sees the labels it is scored
   against.
2. The output is checked before it is scored. A malformed output is a
   `GUARD_FAIL` (the experiment is `invalid`), not a lucky number; NaN
   predictions exit non-zero (the experiment is a `crash`).
3. `_split()` is private and listed in `forbid_patterns`, so a diff that adds a
   call to it is rejected **before** the run. Training on the validation split
   is the most natural-looking way to cheat on this task, and it is a
   two-second rejection rather than a discovery.

`TIME_BUDGET = 3.0` also lives in the frozen file: a better score has to come
from a better idea, not from training longer.

## What the loop finds

From the curated run in [`../../examples/quickstart-run/`](../../examples/quickstart-run/):

| # | change | `val_loss` |
|---|---|---|
| 0 | baseline: multinomial logistic regression | 0.9605 |
| 1 | one hidden layer, 16 tanh units | 0.0511 |
| 2 | widen the hidden layer to 64 | 0.0428 |
| 4 | add polar features (radius, sin/cos of the angle, two harmonics) | 0.0093 |

with a crash (ReLU at learning rate 200 -> NaN), a discard (512 hidden units:
fewer steps in the same 3 seconds), and one `invalid` (training on the val
split).

## Holdout confirmation

This task has `[confirm]` switched on. When an experiment improves `val_loss`,
the harness retrains with `ARH_EVAL_SPLIT=holdout` and only keeps the change if
the holdout score also holds up. That is what makes a keep here worth roughly
twice the compute -- and what stops the loop from slowly fitting the val split.
