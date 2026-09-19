"""The engine's promises:

  * a better score is committed, anything else is reverted to the last keep,
  * every outcome lands in the ledger exactly once,
  * and no experiment can quietly change what "better" means.
"""

import os

import pytest

from arh.engine import Harness, HarnessError
from conftest import SPEC, set_value, write_task


# --------------------------------------------------------------- keep/revert
def test_baseline_is_experiment_zero(harness):
    records = harness.ledger.records()
    assert [r["status"] for r in records] == ["keep"]
    assert records[0]["metric"] == pytest.approx(2.0)  # |5 - 3|
    assert harness.state["best"]["metric"] == pytest.approx(2.0)


def test_improvement_is_kept_and_committed(harness):
    set_value(harness.root, "4.0")
    verdict = harness.run("move VALUE towards the target")
    assert verdict["status"] == "keep"
    assert verdict["metric"] == pytest.approx(1.0)
    assert verdict["delta"] == pytest.approx(-1.0)
    assert "VALUE = 4.0" in (harness.root / "train.py").read_text()
    assert harness.git.head().startswith(verdict["commit"])
    assert "move VALUE towards the target" in harness.git.log()


def test_worse_score_is_reverted(harness):
    set_value(harness.root, "9.0")
    verdict = harness.run("try a much larger value")
    assert verdict["status"] == "discard"
    assert "VALUE = 5.0" in (harness.root / "train.py").read_text(), "the edit must be gone from disk"
    assert harness.state["best"]["metric"] == pytest.approx(2.0)


def test_a_tie_is_discarded(harness):
    set_value(harness.root, "1.0")  # |1-3| == |5-3|
    assert harness.run("mirror the value")["status"] == "discard"


def test_crash_is_recorded_and_reverted(harness):
    (harness.root / "train.py").write_text("raise RuntimeError('bad idea')\n")
    verdict = harness.run("an idea that does not run")
    assert verdict["status"] == "crash" and "exit code 1" in verdict["reason"]
    assert "VALUE = 5.0" in (harness.root / "train.py").read_text()
    assert "bad idea" in verdict["tail"]


def test_nan_is_a_crash_not_a_score(harness):
    set_value(harness.root, "float('nan')")
    verdict = harness.run("diverge")
    assert verdict["status"] == "crash"


def test_timeout_is_a_crash(tmp_path):
    task = write_task(tmp_path / "slow", spec=SPEC.replace("budget_seconds = 20", "budget_seconds = 1"))
    harness = Harness.init(task, tag="t")
    harness.baseline()
    (task / "train.py").write_text("import time\ntime.sleep(30)\n")
    verdict = harness.run("an experiment that never finishes")
    assert verdict["status"] == "crash" and "timeout" in verdict["reason"]
    assert verdict["duration_s"] < 10


def test_nothing_to_evaluate(harness):
    with pytest.raises(HarnessError, match="nothing to evaluate"):
        harness.run("no edit at all")


def test_max_experiments(harness):
    for i in range(25):
        set_value(harness.root, str(10.0 + i))  # always a real edit, always worse
        try:
            harness.run(f"attempt {i}")
        except HarnessError as exc:
            assert "max_experiments" in str(exc)
            return
    raise AssertionError("the experiment limit was never enforced")


# -------------------------------------------------------------------- guards
def test_editing_a_frozen_file_is_invalid_and_undone(harness):
    frozen = harness.root / "prepare.py"
    frozen.write_text(frozen.read_text() + "\n# sneaky\n")
    verdict = harness.run("tune the evaluator a little")
    assert verdict["status"] == "invalid"
    assert "not editable" in verdict["reason"] and "frozen file prepare.py was modified" in verdict["reason"]
    assert "# sneaky" not in frozen.read_text(), "the frozen file must be restored"
    assert verdict["duration_s"] == 0, "guards run before any compute is spent"


def test_a_run_that_rewrites_the_evaluator_is_caught_after_the_fact(harness):
    """The pre-run hash check cannot see code that tampers at runtime; the
    post-run check can."""
    (harness.root / "train.py").write_text(
        "open('prepare.py', 'a').write('\\n# rewritten during the run\\n')\n"
        "from prepare import report\n"
        "report(3.0)\n"
    )
    verdict = harness.run("a trainer that edits the evaluator while it runs")
    assert verdict["status"] == "invalid" and "during the run" in verdict["reason"]
    assert "rewritten during the run" not in (harness.root / "prepare.py").read_text()


def test_forbidden_pattern_in_the_diff(harness):
    path = harness.root / "train.py"
    path.write_text(path.read_text() + '\nprint("METRIC score=0.0")\n')
    verdict = harness.run("report a better number directly")
    assert verdict["status"] == "invalid" and "forbidden pattern 'METRIC'" in verdict["reason"]


def test_a_score_outside_the_bounds_is_invalid(harness):
    set_value(harness.root, "1000.0")
    verdict = harness.run("a value far outside the plausible range")
    assert verdict["status"] == "invalid" and "bounds" in verdict["reason"]


def test_a_duplicated_metric_line_is_invalid(tmp_path):
    spec = SPEC.replace('forbid_patterns = ["METRIC"]', "forbid_patterns = []")
    task = write_task(tmp_path / "dup", spec=spec)
    harness = Harness.init(task, tag="t")
    harness.baseline()
    path = task / "train.py"
    path.write_text(path.read_text() + '\nprint("METRIC score=0.001")\n')
    verdict = harness.run("append a second, better metric line")
    assert verdict["status"] == "invalid" and "reported 2 times" in verdict["reason"]


def test_evaluator_guard_fail_is_invalid(harness):
    """GUARD_FAIL from the frozen evaluator means 'do not trust this number'."""
    set_value(harness.root, "-1.0")  # the toy evaluator refuses negative values
    verdict = harness.run("a model the evaluator refuses to score")
    assert verdict["status"] == "invalid" and "value must not be negative" in verdict["reason"]


def test_new_files_outside_the_allowlist_are_invalid(harness):
    (harness.root / "helper.py").write_text("X = 1\n")
    set_value(harness.root, "4.0")
    verdict = harness.run("split the model into a second file")
    assert verdict["status"] == "invalid" and "helper.py is not editable" in verdict["reason"]


def test_holdout_rejects_an_improvement_that_does_not_generalise(tmp_path):
    spec = SPEC + """
[confirm]
command = "{python} train.py"
env = { ARH_EVAL_SPLIT = "holdout" }
metric = "holdout_score"
tolerance = 0.0
"""
    task = write_task(tmp_path / "holdout", spec=spec)
    harness = Harness.init(task, tag="t")
    harness.baseline()
    set_value(task, "4.2")  # better on val, deliberately worse on the holdout
    verdict = harness.run("a value tuned to the val split")
    assert verdict["status"] == "discard" and "overfitting" in verdict["reason"]
    assert "VALUE = 5.0" in (task / "train.py").read_text()


def test_guard_command_reports_a_dirty_frozen_file(harness):
    frozen = harness.root / "prepare.py"
    frozen.write_text(frozen.read_text() + "\n# tampered\n")
    problems = harness.check()
    assert any("frozen file prepare.py was modified" in p for p in problems)


def test_the_lock_stops_a_second_experiment(harness):
    (harness.state_dir / "lock").write_text(str(os.getpid()))
    set_value(harness.root, "4.0")
    with pytest.raises(HarnessError, match="another arh process"):
        harness.run("concurrent edit")
    (harness.state_dir / "lock").unlink()


def test_the_harness_refuses_to_run_if_someone_else_committed(harness):
    harness.git.run("commit", "--quiet", "--allow-empty", "-m", "a hand-made commit")
    set_value(harness.root, "4.0")
    with pytest.raises(HarnessError, match="HEAD moved"):
        harness.run("after a manual commit")


def test_tampering_during_the_holdout_run_is_still_caught(tmp_path):
    """The last look before a commit: a confirm run that rewrites the evaluator
    must not be able to sneak a keep past the post-run checks."""
    spec = SPEC + """
[confirm]
command = "{python} confirm.py"
metric = "holdout_score"
tolerance = 0.0
"""
    task = write_task(tmp_path / "late", spec=spec)
    (task / "confirm.py").write_text(
        "open('prepare.py', 'a').write('# tampered by the confirm run\\n')\n"
        "print('METRIC holdout_score=0.1')\n"
    )
    harness = Harness.init(task, tag="t")
    verdict = harness.baseline()
    assert verdict["status"] == "invalid" and "before committing" in verdict["reason"]
    assert "tampered by the confirm run" not in (task / "prepare.py").read_text()
