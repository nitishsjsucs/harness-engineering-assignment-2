# Research program: tinygpt (char-level language model)

You are running an autoresearch loop. Lower `val_bpb` -- bits per byte on a
fixed held-out slice of tiny-shakespeare -- by editing `train.py`, one idea at
a time.

## Files

| file | role |
|---|---|
| `train.py` | **editable** -- model, optimiser, batching, schedule, initialisation |
| `prepare.py` | **frozen** -- download, vocabulary, splits, `TIME_BUDGET`, `CONTEXT`, the evaluator |
| `data/` | **frozen by hash** -- the tokenized corpus |

## The fixed rules of this task

- Training gets `prepare.TIME_BUDGET` = 60 seconds of wall clock. More compute
  is not an experiment; it is a different task. The harness kills any run that
  exceeds 180 seconds in total.
- The evaluator scores non-overlapping windows of `prepare.CONTEXT` = 256
  tokens, so the model must accept sequences of that length.
- Before scoring, the evaluator checks that your `forward` is deterministic
  (call `model.eval()`) and causal (rewriting future tokens must not change
  earlier logits). A model that sees the next token scores near zero bits and
  is rejected, not celebrated.
- `prepare.report()` prints the only `METRIC` line. Never print one yourself.
- Train only on `prepare.load_train_tokens()`.

## The loop

1. Read the ledger first (`arh status` / `show_history`). Do not repeat an idea
   that already failed; do not undo a kept improvement.
2. One hypothesis, one focused change, written down in the description.
3. `arh run -m "<description>"` (or the `run_experiment` tool).
4. Read the verdict. Anything but `keep` means the edit is already reverted.
5. Repeat. Do not ask whether to continue; continue.

## Where the wins usually are

The baseline is a 0.84M-parameter, 4-layer, 4-head, 128-dim GPT at learning
rate 1e-3 doing roughly 1100 steps in its 60 seconds. Everything is a trade
against that step count: a bigger model learns more per step and takes fewer
steps. Ideas worth testing include learning-rate schedules (warmup, cosine
decay), the optimiser and its betas/weight decay, batch shape, weight tying
between the embedding and the output head, initialisation scale, normalisation
placement, activation choice, mixed precision, cutting per-step Python
overhead so more of the minute is spent on the GPU, and model shape (depth
versus width versus head count).

Weigh every gain against the complexity it adds. A 0.005 bpb gain that costs
thirty lines of special cases is not worth keeping; the same gain from deleting
code always is.
