# A live run: `gpt-5-mini` driving the loop end to end

2026-09-19, provider `openai`, model `gpt-5-mini`, no human in the loop after
the first command. Every hypothesis below was written by the model; every
number was measured by the harness.

```bash
set -a; . ~/.openai-key.env; set +a          # OPENAI_API_KEY, kept outside the repo
export HARNESS_PROVIDER=openai HARNESS_MODEL=gpt-5-mini
cp -r tasks/quickstart /tmp/live && cd /tmp/live/quickstart
arh init . --tag live && arh baseline && arh loop --agent openai --max 6
```

![progress](progress.png)

## The ledger, as recorded

| # | status | `val_loss` | holdout | the model's own description |
|---|---|---|---|---|
| 0 | keep | 0.960452 | 0.896181 | baseline (unmodified code) |
| 1 | keep | 0.872082 | 0.800115 | "Add quadratic features (x^2, y^2, x*y) to allow simple non-linear boundaries; expect val_loss to drop since spirals need non-linear features." |
| 2 | discard | 0.872086 | -- | "Switch optimizer to Adam (with LR 0.01) for faster, more stable convergence vs plain SGD; expect val_loss to drop by better optimization" |
| 3 | keep | 0.126915 | 0.084197 | "Add polar features (r, sin(theta), cos(theta)) to better capture spiral structure; expect val_loss to drop as model can use angular info." |
| 4 | keep | 0.008474 | 0.007628 | "Add one hidden tanh layer (16 units) with full-batch SGD to give non-linear capacity; expect val_loss to drop as MLP can better separate spirals." |
| 5 | discard | 0.009589 | -- | "Add biases to both layers (b1, b2) and update them with SGD; expect small improvement because biases let the network shift activations and better fit the spiral patterns." |
| 6 | keep | 0.005833 | 0.010511 | "Use SGD with momentum (0.9) instead of plain SGD; expect faster, more stable convergence and lower val_loss within the same time budget." |

**Baseline 0.960452 -> best 0.005833 (-99.4%)** in 3 minutes 16 seconds of wall
clock, 6 experiments, 4 kept, 2 discarded, 0 crashes, 0 guard violations.
49,062 tokens in total (about 8k per experiment). The OpenAI API returns no
price field, so `arh` prints `cost n/a` rather than inventing one.

For comparison, the hand-written script in `../quickstart-run/` reached 0.0093;
the model found 0.0058 on the same task and the same budget, mostly by
stacking polar features and a hidden layer in the right order.

## What is worth pointing at on camera

**Experiment 2 is the honest part.** The model implemented Adam properly --
`runs/0002.diff` is a real Adam, moments, bias correction and all -- and the
harness measured it at 0.872086 against a best of 0.872082: four millionths
*worse*. A linear model on this data converges either way inside the 3-second
budget, so the optimiser change bought nothing. Nobody had to argue about it;
the edit was reverted in 3 seconds and the loop moved on. In a notebook this is
exactly the change that gets kept because it "should" help.

**No guard fired during this run.** The model never tried to edit `prepare.py`,
never reached for the val split, never printed a `METRIC` line of its own. That
is the honest result: the guards are there for the run where it does, and the
scripted example next door shows what that looks like. Nothing here was staged.

**One thing the run exposed.** Experiment 6 was kept although its holdout score
(0.010511) is worse than experiment 4's (0.007628), because the quickstart
task's `[confirm].tolerance` is an *absolute* 0.05 -- a number chosen when
losses were around 0.9, and effectively inert once they reached 0.006. An
absolute tolerance does not survive three orders of magnitude of progress; a
relative one would. This is a task-configuration bug, not an engine bug, and it
is listed in the README's limitations rather than quietly fixed after the fact.

## What is in here

Same layout as `../quickstart-run/`: `results.tsv`, `experiments.jsonl`,
`runs/000N.{log,diff,confirm.log}`, `progress.png`, `report.md`, `state.json`,
and `best-train.py` (the model's final `train.py`). The only post-run edit is
that the temporary directory in the logs was rewritten to `/tmp/live/quickstart`.
