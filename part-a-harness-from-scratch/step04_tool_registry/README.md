# Step 04: a tool registry with derived schemas

**Goal:** add tools without writing (or maintaining) JSON schemas, and make tool
failures survivable.

**The idea (our twist):** a `@tool` decorator reads the function's type hints and
Google-style docstring and produces the schema. The function is the single source
of truth, so the schema can never drift from the code. A second idea rides along:
`run_tool` never raises - unknown tool, broken JSON, wrong arguments and
exceptions all come back as `"Error: ..."` strings, which is exactly the format
the model can read and correct.

## The code

`nanoharness/registry.py`:

```python
def tool(fn):
    TOOLS[fn.__name__] = {"fn": fn, "schema": schema_for(fn)}
    return fn
```

Why: registration happens at import time, and the function stays an ordinary
function you can call and unit-test.

```python
for name, param in inspect.signature(fn).parameters.items():
    prop = json_type(hints.get(name, str))
    if name in arg_docs:
        prop["description"] = arg_docs[name]
    properties[name] = prop
    if param.default is inspect.Parameter.empty:
        required.append(name)  # no default means the model must supply it
```

Why: "has a default" and "is optional" are the same statement in Python and in
JSON Schema, so the two stay in sync for free.

```python
if origin is typing.Literal:
    return {"type": "string", "enum": list(args)}  # a closed set of values
```

Why: an enum in the schema is the cheapest way to stop a model inventing values.
Step 09 uses it for todo statuses.

```python
try:
    inspect.signature(entry["fn"]).bind(**arguments)
except TypeError as err:
    return f"Error: wrong arguments for {name}: {err}."
```

Why: bind first, call second. Otherwise a `TypeError` raised *inside* a tool
would be reported as a bad-arguments error and the model would "fix" the wrong
thing.

```python
except Exception as err:  # a buggy tool must not kill the agent
    return f"Error: {name} failed with {type(err).__name__}: {err}"
```

Why: **errors as results** is the rule that makes the loop in step 05 robust. A
raised exception ends the turn; a string is just another observation, and models
are good at reacting to `FileNotFoundError`.

## Run it

```bash
source ../../.venv/bin/activate
python -m nanoharness
you> which file in this folder is the biggest, and what is in its first 20 lines?
python -m pytest -q test_step.py
```

## What you should see

```text
nanoharness step04 | openrouter | google/gemini-3.5-flash | tools: bash, list_dir, read_file | /exit to quit

you> list this directory

[list_dir] {"path": "."}
nanoharness/
README.md  (3120 bytes)
test_step.py  (4210 bytes)
[the model has not seen this yet - ask it a follow-up question]
```

## Diff from previous step

| File | Change |
|---|---|
| `nanoharness/registry.py` | new: `@tool`, `schema_for`, `json_type`, `parse_docstring`, `run_tool` |
| `nanoharness/tools.py` | rewritten: `bash`, `read_file`, `list_dir` as decorated functions, no hand-written schema |
| `nanoharness/cli.py` | sends `registry.schemas()`, dispatches through `registry.run_tool` |
| `test_step.py` | rewritten: schema derivation, docstring parsing, the four error paths |
| `README.md` | this file |

## Gotchas

- `typing.get_type_hints` resolves string annotations, so `from __future__ import
  annotations` in a tool module still works.
- Tool *descriptions are prompt text*. If a model keeps misusing a tool, fix the
  docstring before you touch the loop.
- `run_tool` returns `str(result)`, so a tool may return any object, but only its
  text ever reaches the model.
