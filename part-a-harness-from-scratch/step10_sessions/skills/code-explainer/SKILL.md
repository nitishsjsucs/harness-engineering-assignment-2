---
name: code-explainer
description: Explain how a file, module or feature works, with a call-path walkthrough and file:line references. Use when the user asks "how does X work" or "walk me through Y".
---

# Code explainer

Produce an explanation a new contributor could follow, grounded in the real files.

## Steps

1. Find the entry point. `list_dir` the relevant directory, then `read_file` the
   file the user named. Do not guess at code you have not read.
2. Follow the call path one hop at a time. For each hop note the file and the
   line number you are quoting.
3. Look for the state: what is held in memory, what is written to disk, what is
   sent over the network.
4. Only then write the explanation.

## Output format

- **What it does** - two or three sentences, no jargon.
- **The path** - a numbered list, each item `file.py:LINE - what happens here`.
- **A diagram** - a small ASCII flow, at most six boxes.
- **Gotchas** - the two or three things that would surprise a reader: ordering
  requirements, silent failures, anything that looks wrong but is deliberate.

## Rules

- Quote code only where the exact text matters, at most five lines per quote.
- If something is unclear from the code, say so instead of inventing a reason.
- Never change a file while explaining it.
