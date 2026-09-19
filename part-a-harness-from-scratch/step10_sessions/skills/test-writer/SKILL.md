---
name: test-writer
description: Write or extend pytest tests for a module, then run them until they pass. Use when the user asks for tests, coverage of an edge case, or a regression test for a bug.
---

# Test writer

Tests are the only way this harness can check its own work. Write them so they
fail for one reason each.

## Steps

1. `read_file` the module under test. List the behaviours it promises, including
   the error paths.
2. Check for an existing test file (`tests/test_<module>.py` or
   `test_<module>.py` next to the code) and follow its style.
3. Write one test per behaviour. Name them `test_<behaviour>`, not `test_1`.
   Cover: the happy path, one boundary, one failure the code handles on purpose.
4. Run `python -m pytest -q <file>` with the bash tool.
5. If a test fails, decide whether the test or the code is wrong, fix that one
   thing, and run again. Repeat at most three times, then report what is left.

## Rules

- Do not change the code under test unless the user asked for a fix; a failing
  test is information, not a problem to hide.
- No network, no sleeping, no reliance on the current time or on file order.
- Use `tmp_path` for anything that touches the filesystem.
- Finish with a one-line summary: how many tests, what they cover, what is still
  untested.
