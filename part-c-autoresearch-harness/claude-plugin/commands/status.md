---
description: Show where the autoresearch loop stands - best score, recent experiments, guard state.
argument-hint: [task-dir]
allowed-tools: Bash, Read
---

# Autoresearch status

!`arh status ${1:+-C "$1"} 2>&1`

Guards right now:

!`arh guard ${1:+-C "$1"} 2>&1`

Pending edit that the next `arh run` would evaluate:

!`arh diff ${1:+-C "$1"} 2>&1 | head -60`

Summarise for the user in a few lines: baseline versus best, how many
experiments were kept out of how many, what the last few results were, and
whether there is an unmeasured edit sitting in the working tree. If a guard is
firing, explain which one and what it means -- do not suggest working around it.
