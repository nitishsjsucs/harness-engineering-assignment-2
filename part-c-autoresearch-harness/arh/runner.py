"""Run one command under a hard wall-clock budget and parse what it reports.

Output protocol (plain stdout lines, so any language can take part):

    METRIC val_bpb=1.873            one or more name=value pairs per line
    GUARD_FAIL model is not causal   the frozen evaluator refuses to score

A task may instead write metrics.json ({"val_bpb": 1.873}) in its directory.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

METRIC_LINE = re.compile(r"^METRIC\s+(.+)$")
PAIR = re.compile(r"([A-Za-z_][\w.\-]*)=(\S+)")
GUARD_LINE = re.compile(r"^GUARD_FAIL\s*(.*)$")


@dataclass
class RunResult:
    returncode: int | None
    timed_out: bool
    duration: float
    log_path: Path
    metrics: dict = field(default_factory=dict)  # name -> list of every value reported
    guard_failures: list = field(default_factory=list)

    def tail(self, n: int = 30) -> str:
        lines = self.log_path.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])


def parse_output(text: str) -> tuple[dict, list]:
    """Collect every METRIC value (a list per name, so duplicates are visible
    to the guards) and every GUARD_FAIL reason."""
    metrics: dict[str, list[float]] = {}
    guard_failures = []
    for line in text.splitlines():
        line = line.strip()
        if m := METRIC_LINE.match(line):
            for name, value in PAIR.findall(m.group(1)):
                metrics.setdefault(name, []).append(_to_float(value))
        elif m := GUARD_LINE.match(line):
            guard_failures.append(m.group(1) or "evaluator refused to score")
    return metrics, guard_failures


def _to_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return math.nan


def run_command(
    command: str,
    cwd: Path,
    log_path: Path,
    budget_seconds: float,
    env: dict | None = None,
    stream: bool = False,
) -> RunResult:
    """Run `command` in its own process group; kill the whole group on timeout.

    A new session matters: training scripts spawn dataloader workers, and
    killing only the shell would leave them burning the next run's budget.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    full_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for key, value in (env or {}).items():
        # None means "make sure this is NOT set" (e.g. a holdout switch that
        # happens to live in the caller's shell).
        if value is None:
            full_env.pop(key, None)
        else:
            full_env[key] = value
    started_wall = time.time()
    start = time.monotonic()
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pump = threading.Thread(target=_pump, args=(proc.stdout, log, stream), daemon=True)
        pump.start()
        timed_out = False
        try:
            proc.wait(timeout=budget_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
        pump.join(timeout=5)
    duration = time.monotonic() - start

    text = log_path.read_text(errors="replace")
    metrics, guard_failures = parse_output(text)
    if not metrics:
        metrics = _read_metrics_json(cwd / "metrics.json", since=started_wall)
    if timed_out:
        with open(log_path, "a") as log:
            log.write(f"\n[arh] killed after {budget_seconds:.0f}s budget\n")
    return RunResult(
        returncode=None if timed_out else proc.returncode,
        timed_out=timed_out,
        duration=duration,
        log_path=log_path,
        metrics=metrics,
        guard_failures=guard_failures,
    )


def _pump(pipe, log, stream: bool) -> None:
    try:
        for chunk in iter(pipe.readline, b""):
            log.write(chunk)
            log.flush()
            if stream:
                sys.stdout.write(chunk.decode(errors="replace"))
                sys.stdout.flush()
    except ValueError:
        # The log was closed because a process that escaped the group kept the
        # pipe open past the budget; the run is already over, so just stop.
        pass
    finally:
        pipe.close()


def _kill_group(proc: subprocess.Popen) -> None:
    for sig, grace in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _read_metrics_json(path: Path, since: float) -> dict:
    # Only trust a metrics.json written by *this* run, never a stale one.
    if not path.is_file() or path.stat().st_mtime < since:
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {str(k): [_to_float(str(v))] for k, v in data.items()}
