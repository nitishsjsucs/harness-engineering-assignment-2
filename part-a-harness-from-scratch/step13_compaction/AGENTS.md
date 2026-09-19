# Project instructions for coding agents

This directory is one step of the nanoharness course. The harness reads this file
at startup and puts it in the system prompt, so keep it short and imperative.

## How to work here

- Run the tests with `python -m pytest -q test_step.py`. They must stay offline:
  no API key, no network.
- Source lives in `nanoharness/`. Keep every file small and single-purpose; each
  one is walked through on video.
- Comments explain *why*, not what.
- Put throwaway files in `scratch/` so the step directory stays clean.

## House rules

- Never edit anything under `.git/`.
- No emojis in code.
- Prefer `edit_file` over rewriting a whole file with `write_file`.
