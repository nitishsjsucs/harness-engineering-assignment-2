# `examples/`

Curated output from real runs, committed so the repository shows what the loop
produces without anyone having to run it first.

- [`quickstart-live-gpt5mini/`](quickstart-live-gpt5mini/) -- **a live run**:
  `gpt-5-mini` proposing every experiment through `arh loop`, 2026-09-19.
  0.960 -> 0.0058 in 3 minutes, 4 kept, 2 discarded, including a correct Adam
  implementation that measured four millionths worse than plain SGD.
- [`quickstart-live-openrouter-free/`](quickstart-live-openrouter-free/) -- the
  same thing on the free default (`deepseek/...:free`): **zero experiments in
  10 requests**, because the model read files instead of proposing changes. Kept
  because an empty ledger is a real result, and because it is the clearest
  evidence that the proposer is a swappable part.
- [`quickstart-run/`](quickstart-run/) -- eight experiments on the same task
  from hand-written hypotheses replayed through the real loop, which is why it
  contains the things a well-behaved model did not do: a divergence crash and a
  reward hack the guards rejected.

Both carry the ledger, the per-run logs and diffs, the progress chart and the
generated report. How each was produced is documented in its own README.
