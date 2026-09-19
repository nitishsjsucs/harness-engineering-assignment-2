"""The runner has one job the rest of the harness depends on: bound the damage
of a single run (time, stray processes) and report exactly what it saw."""

import json
import os
import time

from arh.runner import parse_output, run_command


def test_parses_every_metric_pair_and_guard_line():
    metrics, guards = parse_output(
        "noise\nMETRIC val_bpb=1.5 steps=10\nMETRIC val_bpb=0.1\nGUARD_FAIL not causal\n"
    )
    assert metrics["val_bpb"] == [1.5, 0.1], "duplicates are kept so the engine can reject them"
    assert metrics["steps"] == [10.0]
    assert guards == ["not causal"]


def test_success(tmp_path, python):
    result = run_command(f'{python} -c "print(\'METRIC score=2.0\')"', tmp_path, tmp_path / "r.log", 20)
    assert result.returncode == 0 and not result.timed_out
    assert result.metrics["score"] == [2.0]
    assert "METRIC score=2.0" in result.log_path.read_text()


def test_non_zero_exit_is_visible(tmp_path, python):
    result = run_command(f'{python} -c "raise SystemExit(3)"', tmp_path, tmp_path / "r.log", 20)
    assert result.returncode == 3 and not result.metrics


def test_timeout_kills_the_whole_process_group(tmp_path, python):
    """A training script that spawns workers must not outlive its budget."""
    script = (
        "import subprocess, sys, time;"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "open('child.pid', 'w').write(str(child.pid));"
        "time.sleep(60)"
    )
    result = run_command(f'{python} -c "{script}"', tmp_path, tmp_path / "r.log", budget_seconds=1.5)
    assert result.timed_out and result.returncode is None
    assert result.duration < 10

    child_pid = int((tmp_path / "child.pid").read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return  # the grandchild died with the group, which is the point
        time.sleep(0.1)
    raise AssertionError(f"process {child_pid} survived the timeout")


def test_metrics_json_is_a_fallback(tmp_path, python):
    script = f"import json; json.dump({{'score': 4.0}}, open('metrics.json','w'))"
    result = run_command(f'{python} -c "{script}"', tmp_path, tmp_path / "r.log", 20)
    assert result.metrics["score"] == [4.0]


def test_stale_metrics_json_is_ignored(tmp_path, python):
    (tmp_path / "metrics.json").write_text(json.dumps({"score": 99.0}))
    os.utime(tmp_path / "metrics.json", (time.time() - 600, time.time() - 600))
    result = run_command(f'{python} -c "pass"', tmp_path, tmp_path / "r.log", 20)
    assert result.metrics == {}


def test_env_value_none_unsets_a_variable(tmp_path, python, monkeypatch):
    monkeypatch.setenv("ARH_EVAL_SPLIT", "holdout")
    script = "import os; print('METRIC seen=%d' % ('ARH_EVAL_SPLIT' in os.environ))"
    result = run_command(f'{python} -c "{script}"', tmp_path, tmp_path / "r.log", 20, env={"ARH_EVAL_SPLIT": None})
    assert result.metrics["seen"] == [0.0]
