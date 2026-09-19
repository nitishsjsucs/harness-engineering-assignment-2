#!/usr/bin/env python3
"""Run every step's offline test suite and print a pass/fail table.

    python run_tests.py            # all fifteen steps
    python run_tests.py 5 6 7      # only those steps
    python run_tests.py 11-15      # a range

Each step is run in its own subprocess with that step directory as the working
directory, because all fifteen steps contain a package called `nanoharness` and
only one of them may be imported per process.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def step_directories() -> list[Path]:
    return sorted(path for path in HERE.glob("step*_*") if (path / "test_step.py").is_file())


def wanted(arguments: list[str]) -> set[int] | None:
    """Parse "5", "11-15" and "07" into a set of step numbers. None means all."""
    if not arguments:
        return None
    numbers: set[int] = set()
    for argument in arguments:
        match = re.fullmatch(r"(\d+)-(\d+)", argument)
        if match:
            numbers.update(range(int(match.group(1)), int(match.group(2)) + 1))
        elif argument.isdigit():
            numbers.add(int(argument))
        else:
            print(f"ignoring argument {argument!r}: expected a number or a range like 11-15")
    return numbers


def number_of(directory: Path) -> int:
    return int(directory.name[4:6])


def run(directory: Path) -> tuple[bool, str, float]:
    started = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_step.py"],
        cwd=directory,
        capture_output=True,
        text=True,
        env={**_clean_env(), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    summary = last_summary_line(result.stdout) or (result.stderr.strip().splitlines() or ["no output"])[-1]
    return result.returncode == 0, summary, time.time() - started


def _clean_env() -> dict:
    import os

    # Keep the tests honest: no key in the environment, ever.
    return {key: value for key, value in os.environ.items() if key not in ("OPENROUTER_API_KEY", "GEMINI_API_KEY")}


def last_summary_line(output: str) -> str:
    for line in reversed(output.strip().splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            return line.strip().replace("=", "").strip()
    return ""


def main(argv: list[str]) -> int:
    selection = wanted(argv)
    directories = [d for d in step_directories() if selection is None or number_of(d) in selection]
    if not directories:
        print("no matching steps")
        return 1

    print(f"{'step':<34}{'result':<10}{'summary':<28}{'seconds':>8}")
    print("-" * 80)
    failures = []
    for directory in directories:
        passed, summary, seconds = run(directory)
        print(f"{directory.name:<34}{'PASS' if passed else 'FAIL':<10}{summary[:27]:<28}{seconds:>8.2f}")
        if not passed:
            failures.append(directory.name)
    print("-" * 80)
    print(f"{len(directories) - len(failures)}/{len(directories)} steps passed")
    if failures:
        print("failed: " + ", ".join(failures))
        print("re-run one with: cd <step> && python -m pytest -q test_step.py")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
