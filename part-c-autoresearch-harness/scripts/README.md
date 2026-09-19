# `scripts/`

| file | what it is |
|---|---|
| `demo_quickstart.sh` | the whole loop end to end on a temporary copy of the quickstart task: init, baseline, several experiments, status, guard, report. About a minute. |
| `quickstart_demo.json` | seven hand-written experiments, replayed through the real agent loop by `arh loop --agent scripted`. |

```bash
./scripts/demo_quickstart.sh              # offline: scripted proposer
./scripts/demo_quickstart.sh openrouter   # live model (needs OPENROUTER_API_KEY)
```

## The script format

```json
[
  {
    "thought": "why this experiment",
    "description": "what goes in the ledger",
    "edits": [{"path": "train.py", "old": "HIDDEN = 16", "new": "HIDDEN = 64"}]
  }
]
```

`edits` entries are `{path, old, new}` for `edit_file`, or `{path, content}`
with `"tool": "write_file"` for a whole-file rewrite.
`ScriptedModel.from_experiment_script` turns each entry into the same tool
calls a live model would emit, so the harness cannot tell the difference: the
permission checks, the engine and the guards all run for real.

A script says what to *change*. It cannot say what the result should be -- that
is measured. This is why the scripted run in `examples/quickstart-run/`
contains a crash and a rejected reward hack that were not planned as such.
