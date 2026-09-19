---
description: Write progress.png and report.md for an autoresearch task and summarise the findings.
argument-hint: [task-dir]
allowed-tools: Bash, Read
---

# Autoresearch report

!`arh report ${1:+-C "$1"} 2>&1`

Now:

1. Read the generated `report.md` (the command above prints its path) and, if
   it helps you describe the shape of the run, look at `progress.png`.
2. Write a short summary for the user:
   - baseline -> best, in the task's own metric and as a percentage;
   - the kept improvements in order, one line each, with the number attached;
   - what failed and what that rules out (crashes, discards, guard hits);
   - the two or three most promising things to try next, and why;
   - anything about the measurement itself that the user should not trust
     (noise, a single-run keep, a holdout that was not configured).
3. Point the user at `.arh/results.tsv` and `.arh/experiments.jsonl` as the
   durable record, and at `.arh/runs/<id>.log` / `.arh/runs/<id>.diff` for any
   experiment they want to inspect.
