"""Step 04: one decorator that turns a typed, documented function into a tool.

Writing JSON schemas by hand (step 03) drifts from the code within a day. Here
the function *is* the source of truth: type hints become JSON types, the
docstring becomes the description the model reads, and `run_tool` is the single
door through which the model's requests pass.
"""
import inspect
import json
import re
import typing

# name -> {"fn": callable, "schema": {...}}
TOOLS: dict[str, dict] = {}

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}


def tool(fn):
    """Register a function as a tool. The schema is derived, never written by hand."""
    TOOLS[fn.__name__] = {"fn": fn, "schema": schema_for(fn)}
    return fn


def schemas(names: list[str] | None = None) -> list[dict]:
    """The `tools=[...]` payload for the API, optionally restricted to some names."""
    chosen = TOOLS if names is None else {n: TOOLS[n] for n in names if n in TOOLS}
    return [entry["schema"] for entry in chosen.values()]


def schema_for(fn) -> dict:
    summary, arg_docs = parse_docstring(fn.__doc__ or "")
    hints = typing.get_type_hints(fn)
    properties, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        prop = json_type(hints.get(name, str))
        if name in arg_docs:
            prop["description"] = arg_docs[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)  # no default means the model must supply it
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": summary,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def json_type(annotation) -> dict:
    """Map a Python annotation to a JSON Schema fragment."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Literal:
        return {"type": "string", "enum": list(args)}  # a closed set of values
    if origin in (list, set, tuple):
        return {"type": "array", "items": json_type(args[0]) if args else {}}
    if typing.is_typeddict(annotation):
        fields = typing.get_type_hints(annotation)
        return {
            "type": "object",
            "properties": {name: json_type(tp) for name, tp in fields.items()},
            "required": sorted(annotation.__required_keys__),
        }
    return {"type": JSON_TYPES.get(annotation, "string")}


ARG_LINE = re.compile(r"\s+(\w+)\s*(?:\([^)]*\))?:\s*(.*)")


def parse_docstring(doc: str) -> tuple[str, dict]:
    """Split a Google-style docstring into (summary, {arg: description})."""
    text = inspect.cleandoc(doc)
    summary, _, args_block = text.partition("Args:")
    descriptions: dict[str, str] = {}
    current = None
    for line in args_block.splitlines():
        if line and not line[0].isspace():
            break  # a new unindented section ("Returns:", "Notes:") ends the argument list
        match = ARG_LINE.match(line)
        if match:
            current = match.group(1)
            descriptions[current] = match.group(2).strip()
        elif current and line.strip():
            descriptions[current] += " " + line.strip()  # wrapped line
    return " ".join(summary.split()), descriptions


def run_tool(name: str, raw_arguments: str) -> str:
    """Run one tool call. Never raises - every failure becomes text for the model.

    An exception here would end the turn; a string keeps the loop alive and lets
    the model fix its own mistake on the next step.
    """
    entry = TOOLS.get(name)
    if entry is None:
        return f"Error: no tool named {name!r}. Available tools: {', '.join(sorted(TOOLS))}."
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as err:
        return f"Error: the arguments for {name} are not valid JSON ({err}). Send a JSON object."
    if not isinstance(arguments, dict):
        return f"Error: the arguments for {name} must be a JSON object, got {type(arguments).__name__}."
    try:
        inspect.signature(entry["fn"]).bind(**arguments)
    except TypeError as err:
        return f"Error: wrong arguments for {name}: {err}."
    try:
        return str(entry["fn"](**arguments))
    except Exception as err:  # a buggy tool must not kill the agent
        return f"Error: {name} failed with {type(err).__name__}: {err}"
