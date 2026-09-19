"""arh -- an end-to-end ML autoresearch harness.

The package is split by responsibility so each file can be read on its own:

    spec.py     what a task is (autoresearch.toml)
    runner.py   run one command under a wall-clock budget, parse METRIC lines
    ledger.py   append-only results.tsv + experiments.jsonl
    gitops.py   branch / commit / restore, isolated or inside your repo
    guards.py   anti reward-hacking checks (hashes, allowlist, diff scan, bounds)
    engine.py   the keep-or-revert decision that ties the above together
    report.py   progress.png + report.md
    models.py   chat models: OpenRouter (live) and Scripted (offline)
    agent.py    headless proposer: a tool-calling loop over a chat model
    cli.py      the `arh` command
"""

__version__ = "0.1.0"
