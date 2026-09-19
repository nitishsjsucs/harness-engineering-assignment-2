# `tinygpt` -- the laptop-sized version of the real thing

A character-level GPT on tiny-shakespeare, trained for exactly 60 seconds per
experiment and scored in bits per byte on a fixed held-out slice. This is
Karpathy's autoresearch task shrunk until an experiment fits in a laptop
minute, with the rules enforced by the harness instead of stated in a prompt.

```bash
pip install -e ".[torch]"            # torch is only needed for this task
cp -r tasks/tinygpt /tmp/gpt && cd /tmp/gpt
arh init . --tag sep19               # downloads + verifies + tokenizes (once)
arh baseline                         # about 61 s
```

Measured on an Apple M-series laptop (MPS):

```
experiment #0: KEEP  val_bpb=2.50009  [61.4s]
```

0.84M parameters, 4 layers, 4 heads, 128 dims, roughly 1100 steps in the
minute. A second run of the identical code scored 2.5258, so **run-to-run noise
is about 0.026 bpb** -- `min_delta` is set to 0.02 and a single-run keep should
still be treated as provisional.

## Data

`prepare.py` downloads tiny-shakespeare (1,115,394 characters, 65 distinct),
checks its SHA-256 against a pinned value, falls back to a second mirror, and
accepts a local copy via `TINYSHAKESPEARE_PATH` for an offline machine. It then
builds the vocabulary, splits 90/10 and writes `data/*.npy`.

The token files are not in git, so they are protected by hash instead:

```toml
integrity = ["data/train.npy", "data/val.npy", "data/meta.json"]
```

If a run rewrites the validation tokens, the experiment is `invalid`.

## The evaluator is the interesting file

`evaluate_bpb()` takes a callable, feeds it inputs only, and computes the
cross-entropy itself. Before it trusts the model at all, it runs two probes:

```python
first = _logits(forward, x, vocab_size)
if not torch.allclose(first, _logits(forward, x, vocab_size), atol=1e-5):
    raise LeakError("forward is not deterministic; put the model in eval() mode (dropout off)")
cut = x.shape[1] // 2
perturbed = x.clone()
perturbed[:, cut:] = noise
after = _logits(forward, perturbed, vocab_size)
if not torch.allclose(first[:, :cut], after[:, :cut], atol=1e-4):
    raise LeakError("the model attends to future tokens; the evaluation only scores causal models")
```

The second probe is the one that matters. Removing the causal mask -- an easy
"optimisation" to make by accident -- lets the model read the answer, and it
would score near zero bits per byte. That looks like a breakthrough and is a
bug. Verified by hand: with `is_causal=False`, the evaluator refuses to score
and the harness records the experiment as `invalid`.

Two more rules the evaluator enforces: it scores fixed 256-token windows
(`CONTEXT`), so a model that shrinks its context is measured honestly, and
`TIME_BUDGET = 60` lives here rather than in `train.py`.

## What to try

The baseline is deliberately plain: constant learning rate, no warmup, no
weight decay tuning, no weight tying, batch built in Python every step. The
trade is always against the step count -- a bigger model learns more per step
and takes fewer of them in the same minute. `program.md` lists the usual
suspects.

## Holdout

`[confirm]` is present but commented out: confirming a keep means retraining
for another 60 seconds. `prepare.py` already supports it -- `ARH_EVAL_SPLIT=holdout`
scores the back of the val split instead of the front -- so uncommenting the
section is all it takes to trade speed for a stronger guard.
