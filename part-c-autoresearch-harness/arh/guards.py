"""Anti reward-hacking guards.

An optimiser pointed at a number will find the cheapest way to move it, and
editing the ruler is usually cheaper than improving the model. Each guard
below closes one such shortcut. They are deliberately dumb, deterministic
checks: the harness enforces them in code, so no prompt can talk its way past.

    frozen hashes      evaluation code / data prep did not change (before AND after the run)
    integrity hashes   untracked artefacts such as the val split did not change
    allowlist          the diff touches only [files].editable
    forbidden patterns added lines do not print METRIC lines or reach for eval data
    bounds             the score is physically plausible
    duration           a run that is far faster than usual probably skipped training
    (holdout)          lives in engine.py: a new best must also hold on unseen data
"""

from __future__ import annotations

import hashlib
import math
import statistics
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_files(root: Path, patterns) -> dict[str, str]:
    """{relative path: sha256} for every file matching the patterns."""
    hashes = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)) if any(c in pattern for c in "*?[") else [root / pattern]:
            if path.is_file():
                hashes[path.relative_to(root).as_posix()] = sha256(path)
    return hashes


def check_hashes(root: Path, expected: dict[str, str], patterns, label: str) -> list[str]:
    current = hash_files(root, patterns)
    problems = []
    for rel, digest in expected.items():
        if rel not in current:
            problems.append(f"{label} file {rel} was deleted")
        elif current[rel] != digest:
            problems.append(f"{label} file {rel} was modified")
    for rel in sorted(set(current) - set(expected)):
        problems.append(f"new file {rel} matches a {label} pattern")
    return problems


def check_allowlist(changed: list[str], spec) -> list[str]:
    return [
        f"{rel} is not editable (allowed: {', '.join(spec.editable)})"
        for rel in changed
        if not spec.is_editable(rel)
    ]


def scan_diff(diff_text: str, patterns) -> list[str]:
    """Look only at lines the experiment *adds*: removing a bad line is fine."""
    problems = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            for pattern in patterns:
                if pattern in line:
                    problems.append(f"added line contains forbidden pattern {pattern!r}: {line[1:].strip()[:80]}")
    return problems


def check_bounds(value: float, bounds: tuple[float, float]) -> str | None:
    low, high = bounds
    if not (low <= value <= high):
        return f"metric {value:.6g} is outside plausible bounds [{low:g}, {high:g}]"
    return None


def check_duration(duration: float, reference_durations: list[float], fraction: float) -> str | None:
    """Borrowed from evo's verifier: a run that finishes in a fraction of the
    usual time has usually short-circuited (cached result, skipped training)."""
    if fraction <= 0 or not reference_durations:
        return None
    typical = statistics.median(reference_durations)
    if duration < fraction * typical:
        return f"run took {duration:.1f}s, under {fraction:.0%} of the typical {typical:.1f}s"
    return None


def is_finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)
