"""The task spec is the harness's constitution: if it loads wrong, every later
guarantee is void. These tests pin the rules it must enforce."""

import pytest

from arh.spec import SpecError, load_spec, matches
from conftest import SPEC, write_task


def test_loads_the_contract(task_dir):
    spec = load_spec(task_dir)
    assert spec.name == "toy"
    assert spec.editable == ("train.py",) and spec.frozen == ("prepare.py",)
    assert spec.metric == "score" and spec.direction == "min"
    assert spec.bounds == (0.0, 100.0)
    assert spec.max_experiments == 20
    assert "{python}" not in spec.expand(spec.command)


def test_missing_spec(tmp_path):
    with pytest.raises(SpecError, match="no autoresearch.toml"):
        load_spec(tmp_path)


def test_a_file_cannot_be_editable_and_frozen(tmp_path):
    spec = SPEC.replace('frozen = ["prepare.py"]', 'frozen = ["prepare.py", "train.py"]')
    write_task(tmp_path / "t", spec=spec)
    with pytest.raises(SpecError, match="both editable and frozen"):
        load_spec(tmp_path / "t")


def test_listed_files_must_exist(tmp_path):
    spec = SPEC.replace('editable = ["train.py"]', 'editable = ["train.py", "model.py"]')
    write_task(tmp_path / "t", spec=spec)
    with pytest.raises(SpecError, match="do not exist"):
        load_spec(tmp_path / "t")


def test_direction_must_be_min_or_max(tmp_path):
    write_task(tmp_path / "t", spec=SPEC.replace('direction = "min"', 'direction = "lower"'))
    with pytest.raises(SpecError, match="min.*max"):
        load_spec(tmp_path / "t")


def test_is_better_respects_direction_and_min_delta(task_dir):
    spec = load_spec(task_dir)
    assert spec.is_better(1.0, 2.0) and not spec.is_better(2.0, 1.0)
    assert not spec.is_better(2.0, 2.0), "a tie is never an improvement"


@pytest.mark.parametrize(
    "path,patterns,expected",
    [
        ("train.py", ["train.py"], True),
        ("sub/train.py", ["train.py"], False),  # a literal never leaks to a nested file
        ("sub/train.py", ["sub/*.py"], True),
        ("data/val.npy", ["data/"], True),
        ("a/data/val.npy", ["data/"], True),
        ("notes.pyc", ["*.pyc"], True),
        ("deep/notes.pyc", ["*.pyc"], True),
        (".arh/state.json", [".arh/"], True),
        ("train.py", ["prepare.py"], False),
    ],
)
def test_path_matching(path, patterns, expected):
    assert matches(path, patterns) is expected
