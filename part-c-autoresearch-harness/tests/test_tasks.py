"""The shipped tasks: their specs must load, and the quickstart evaluator must
refuse the outputs it is supposed to refuse.

tinygpt is not trained here (it needs torch and a minute of GPU time); only its
spec and its rules are checked.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from arh.spec import load_spec

TASKS = Path(__file__).resolve().parents[1] / "tasks"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def quickstart():
    import sys

    sys.path.insert(0, str(TASKS / "quickstart"))
    import prepare  # noqa: E402

    return prepare


@pytest.mark.parametrize("name", ["quickstart", "tinygpt"])
def test_shipped_specs_load(name):
    spec = load_spec(TASKS / name)
    assert spec.editable == ("train.py",) and spec.frozen == ("prepare.py",)
    assert "METRIC" in spec.forbid_patterns, "training code must never print the score itself"
    assert spec.bounds[0] > 0, "an implausibly good score should be caught"


def test_the_quickstart_dataset_is_deterministic(quickstart):
    first, second = quickstart._dataset()[0], quickstart._dataset()[0]
    assert np.array_equal(first, second)
    train, val = quickstart._split("train")[0], quickstart._split("val")[0]
    assert len(train) == 2160 and len(val) == 720
    assert not np.array_equal(train[:720], val)


def test_the_evaluator_scores_a_uniform_model_at_chance(quickstart):
    uniform = lambda X: np.full((len(X), 3), 1 / 3)  # noqa: E731
    name, loss = quickstart.evaluate(uniform)
    assert name == "val_loss"
    assert loss == pytest.approx(np.log(3), abs=1e-6)


def test_the_evaluator_refuses_malformed_output(quickstart):
    with pytest.raises(ValueError, match="expected"):
        quickstart.evaluate(lambda X: np.zeros((len(X), 2)))
    with pytest.raises(ValueError, match="sum to 1"):
        quickstart.evaluate(lambda X: np.full((len(X), 3), 0.9))
    with pytest.raises(quickstart.DivergedError):
        quickstart.evaluate(lambda X: np.full((len(X), 3), np.nan))


def test_the_holdout_split_is_selected_by_the_environment(quickstart, monkeypatch):
    monkeypatch.setenv("ARH_EVAL_SPLIT", "holdout")
    name, _ = quickstart.evaluate(lambda X: np.full((len(X), 3), 1 / 3))
    assert name == "holdout_loss"


def test_the_demo_script_is_well_formed():
    steps = json.loads((SCRIPTS / "quickstart_demo.json").read_text())
    assert len(steps) >= 6
    for step in steps:
        assert step["description"]
        for edit in step["edits"]:
            assert edit["path"] == "train.py"
            assert ("old" in edit and "new" in edit) or "content" in edit
    first = steps[0]["edits"][0]["content"]
    assert "HIDDEN = 16" in first, "the first scripted experiment introduces the hidden layer"


def test_tinygpt_keeps_its_data_honest():
    spec = load_spec(TASKS / "tinygpt")
    assert spec.setup, "the data must be prepared by a frozen step, not by the trainer"
    assert spec.integrity, "the tokenized data is protected by hash"
    assert "val.npy" in spec.forbid_patterns
