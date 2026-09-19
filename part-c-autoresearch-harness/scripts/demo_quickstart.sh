#!/usr/bin/env bash
# End-to-end demo of the harness, on a throwaway copy of the quickstart task.
#
#   ./scripts/demo_quickstart.sh            # replay the scripted experiments (offline)
#   ./scripts/demo_quickstart.sh openrouter # let a live model propose (needs OPENROUTER_API_KEY)
#
# Takes about a minute. Nothing is written inside this repository: the task is
# copied to a temporary directory first, which is also how you should run any
# task that lives inside a git repo you care about.
set -euo pipefail

MODE="${1:-scripted}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/arh-demo-XXXXXX")"
ARH="${ARH:-arh}"

echo "== copying tasks/quickstart to $WORK"
cp -r "$HERE/tasks/quickstart" "$WORK/quickstart"
rm -rf "$WORK/quickstart/__pycache__"
cd "$WORK/quickstart"

echo "== arh init (verify the spec, hash the frozen files, create the branch)"
"$ARH" init . --tag demo

echo "== arh baseline (measure the unmodified code)"
"$ARH" baseline

if [ "$MODE" = "openrouter" ]; then
  echo "== arh loop --agent openrouter (a live model proposes the experiments)"
  "$ARH" loop --agent openrouter --max 6
else
  echo "== arh loop --agent scripted (hand-written hypotheses, real engine)"
  "$ARH" loop --agent scripted --script "$HERE/scripts/quickstart_demo.json" --max 8
fi

echo "== arh status"
"$ARH" status

echo "== arh guard (every guard, without running an experiment)"
"$ARH" guard

echo "== arh report"
"$ARH" report

echo
echo "done. the run lives in $WORK/quickstart/.arh"
echo "  ledger : $WORK/quickstart/.arh/results.tsv"
echo "  chart  : $WORK/quickstart/.arh/progress.png"
echo "  history: git --git-dir=$WORK/quickstart/.arh/git --work-tree=$WORK/quickstart log --oneline"
