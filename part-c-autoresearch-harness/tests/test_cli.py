"""The command line is the contract that both humans and Claude Code use."""

import json

import pytest

from arh.cli import main
from conftest import set_value


def test_the_whole_flow(task_dir, capsys):
    assert main(["init", str(task_dir), "--tag", "cli"]) == 0
    assert "autoresearch/cli" in capsys.readouterr().out

    assert main(["baseline", "-C", str(task_dir)]) == 0
    assert "KEEP" in capsys.readouterr().out

    set_value(task_dir, "4.0")
    assert main(["diff", "-C", str(task_dir)]) == 0
    assert "VALUE = 4.0" in capsys.readouterr().out

    assert main(["run", "-C", str(task_dir), "-m", "closer to the target"]) == 0
    assert "KEEP" in capsys.readouterr().out

    assert main(["status", "-C", str(task_dir)]) == 0
    out = capsys.readouterr().out
    assert "best" in out and "closer to the target" in out

    assert main(["guard", "-C", str(task_dir)]) == 0
    assert "all guards pass" in capsys.readouterr().out

    assert main(["report", "-C", str(task_dir)]) == 0
    assert (task_dir / ".arh" / "progress.png").is_file()


def test_run_json_is_machine_readable(harness, capsys):
    set_value(harness.root, "4.0")
    assert main(["run", "-C", str(harness.root), "-m", "closer", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "keep" and record["metric"] == pytest.approx(1.0)


def test_guard_exits_non_zero_when_a_guard_fires(harness, capsys):
    frozen = harness.root / "prepare.py"
    frozen.write_text(frozen.read_text() + "\n# tampered\n")
    assert main(["guard", "-C", str(harness.root)]) == 1
    assert "frozen file prepare.py was modified" in capsys.readouterr().out


def test_errors_are_reported_without_a_traceback(task_dir, capsys):
    assert main(["status", "-C", str(task_dir)]) == 2
    assert "not initialised" in capsys.readouterr().err


def test_dry_run_shows_what_the_model_would_see(harness, capsys):
    assert main(["loop", "-C", str(harness.root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "=== system prompt ===" in out and "run_experiment" in out


def test_loop_with_a_script(harness, tmp_path, capsys):
    script = tmp_path / "s.json"
    script.write_text(json.dumps([{"description": "closer", "edits": [{"path": "train.py", "old": "VALUE = 5.0", "new": "VALUE = 4.0"}]}]))
    assert main(["loop", "-C", str(harness.root), "--agent", "scripted", "--script", str(script), "--max", "1"]) == 0
    assert "1 experiments, 1 kept" in capsys.readouterr().out


def test_scripted_loop_needs_a_script(harness):
    assert main(["loop", "-C", str(harness.root), "--agent", "scripted"]) == 2


def test_a_missing_key_is_an_error_not_a_traceback(harness, capsys, monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert main(["loop", "-C", str(harness.root), "--agent", "openai", "--max", "1"]) == 2
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY is not set" in err and "--agent scripted" in err
