"""Offline test for step 04: schemas are derived, and run_tool never raises."""
import json
from typing import Literal, TypedDict

import pytest

from nanoharness import registry, tools


def test_schema_is_derived_from_hints_and_docstring():
    schema = registry.TOOLS["read_file"]["schema"]["function"]
    assert schema["name"] == "read_file"
    assert schema["description"].startswith("Read a text file")
    properties = schema["parameters"]["properties"]
    assert properties["path"]["type"] == "string"
    assert properties["offset"]["type"] == "integer"
    assert properties["path"]["description"].startswith("File to read")
    # Only parameters without a default are required.
    assert schema["parameters"]["required"] == ["path"]


def test_json_type_covers_lists_literals_and_typed_dicts():
    class Item(TypedDict):
        name: str
        count: int

    assert registry.json_type(list[str]) == {"type": "array", "items": {"type": "string"}}
    assert registry.json_type(Literal["a", "b"]) == {"type": "string", "enum": ["a", "b"]}
    assert registry.json_type(Item) == {
        "type": "object",
        "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
        "required": ["count", "name"],
    }


def test_docstring_parser_stops_at_the_next_section():
    summary, args = registry.parse_docstring(
        """Do a thing.

        Args:
            first: The first one,
                continued on a second line.
            second: The second one.

        Returns:
            Something else entirely.
        """
    )
    assert summary == "Do a thing."
    assert args == {"first": "The first one, continued on a second line.", "second": "The second one."}


def test_unknown_tool_is_an_error_string():
    result = registry.run_tool("delete_the_internet", "{}")
    assert result.startswith("Error: no tool named")
    assert "read_file" in result  # tell the model what it can call instead


def test_broken_json_is_an_error_string():
    assert registry.run_tool("read_file", '{"path": ').startswith("Error: the arguments for read_file are not valid JSON")
    assert registry.run_tool("read_file", '"just a string"').startswith("Error: the arguments for read_file must be a JSON object")


def test_wrong_arguments_are_an_error_string():
    assert registry.run_tool("read_file", "{}").startswith("Error: wrong arguments for read_file")
    assert registry.run_tool("read_file", '{"path": "x", "nope": 1}').startswith("Error: wrong arguments")


def test_exceptions_inside_a_tool_become_error_strings():
    result = registry.run_tool("read_file", '{"path": "/no/such/file"}')
    assert result.startswith("Error: read_file failed with FileNotFoundError")


def test_tools_actually_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.txt").write_text("alpha\nbeta\ngamma\n")
    (tmp_path / "sub").mkdir()

    numbered = registry.run_tool("read_file", json.dumps({"path": "hello.txt"}))
    assert "    1  alpha" in numbered and "    3  gamma" in numbered

    page = registry.run_tool("read_file", json.dumps({"path": "hello.txt", "offset": 2, "limit": 1}))
    assert "    2  beta" in page and "1 more lines" in page

    listing = registry.run_tool("list_dir", "{}")
    assert "sub/" in listing and "hello.txt" in listing

    assert "[exit code 0]" in registry.run_tool("bash", json.dumps({"command": "echo hi"}))


def test_decorator_registers_and_keeps_the_function_callable():
    @registry.tool
    def shout(word: str) -> str:
        """Shout a word.

        Args:
            word: The word.
        """
        return word.upper()

    try:
        assert "shout" in registry.TOOLS
        assert shout("hi") == "HI"  # still an ordinary function
        assert registry.run_tool("shout", '{"word": "hi"}') == "HI"
        assert any(s["function"]["name"] == "shout" for s in registry.schemas())
        assert registry.schemas(["shout"]) == [registry.TOOLS["shout"]["schema"]]
    finally:
        del registry.TOOLS["shout"]


@pytest.mark.parametrize("name", ["bash", "read_file", "list_dir"])
def test_every_schema_is_serialisable(name):
    assert json.dumps(registry.TOOLS[name]["schema"])
    assert tools  # the tools module is what registered them
