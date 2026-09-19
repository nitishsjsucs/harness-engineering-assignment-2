"""Shared fixtures: a toy task that runs in milliseconds.

The toy task has the same shape as a real one (frozen evaluator, editable
trainer, spec) but no numpy, no training and no data, so the whole suite runs
offline in a couple of seconds.

    train.py:   VALUE = 5.0, handed to the frozen evaluator
    prepare.py: score = |VALUE - 3|, printed as the METRIC line (lower is better)
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from arh.engine import Harness

PREPARE = '''
"""FROZEN toy evaluator."""
import os
import sys

TARGET = 3.0


def report(value, **extra):
    score = abs(float(value) - TARGET)
    if score != score:  # NaN: a broken idea, not a broken rule -> crash
        print("training diverged: score is not a number")
        sys.exit(1)
    if float(value) < 0:  # an impossible value -> the evaluator refuses to score
        print("GUARD_FAIL value must not be negative")
        sys.exit(1)
    if os.environ.get("ARH_EVAL_SPLIT") == "holdout":
        # The holdout is deliberately hostile to one particular value, so a
        # test can produce "better on val, worse on the holdout".
        score = 5.0 if float(value) == 4.2 else score
        print(f"METRIC holdout_score={score:.6f}")
        return
    print(f"METRIC score={score:.6f} value={float(value)}")
'''

TRAIN = '''
"""EDITABLE toy trainer."""
from prepare import report

VALUE = 5.0

report(VALUE)
'''

SPEC = """
[task]
name = "toy"
description = "toy task for the test suite"

[files]
editable = ["train.py"]
frozen = ["prepare.py"]

[run]
command = "{python} train.py"
budget_seconds = 20

[metric]
name = "score"
direction = "min"
min_delta = 0.0

[guards]
bounds = [0.0, 100.0]
forbid_patterns = ["METRIC"]

[loop]
max_experiments = 20
"""


def write_task(directory: Path, spec: str = SPEC, train: str = TRAIN, prepare: str = PREPARE) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "autoresearch.toml").write_text(textwrap.dedent(spec))
    (directory / "train.py").write_text(textwrap.dedent(train))
    (directory / "prepare.py").write_text(textwrap.dedent(prepare))
    (directory / "program.md").write_text("# toy program\nMake score smaller by editing train.py.\n")
    return directory


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return write_task(tmp_path / "toy")


@pytest.fixture
def harness(task_dir: Path) -> Harness:
    """An initialised task with its baseline already measured."""
    h = Harness.init(task_dir, tag="test")
    h.baseline()
    return h


def set_value(task_dir: Path, value: str) -> None:
    """The only kind of edit the toy task needs, whatever the current value is."""
    path = task_dir / "train.py"
    path.write_text(re.sub(r"VALUE = .*", f"VALUE = {value}", path.read_text()))


def git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def python() -> str:
    """Quoted, because this repo lives under a path with spaces in it."""
    return shlex.quote(sys.executable)
