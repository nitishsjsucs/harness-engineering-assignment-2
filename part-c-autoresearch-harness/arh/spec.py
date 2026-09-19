"""Task specification: the contract between the researcher and the harness.

Every task directory carries an `autoresearch.toml`. It answers the questions
the harness must never leave to the model: which files may change, which are
evaluation code, how to run, what "better" means, and how long a run may take.
"""

from __future__ import annotations

import fnmatch
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

SPEC_FILE = "autoresearch.toml"
STATE_DIR = ".arh"

# Runtime outputs that are never part of an experiment's diff. The harness owns
# .arh/, and data/ holds downloaded datasets produced by the frozen setup step.
DEFAULT_IGNORE = (".arh/", "data/", "__pycache__/", "*.pyc", ".DS_Store", "metrics.json")


class SpecError(ValueError):
    """The task spec is missing, malformed, or internally inconsistent."""


def matches(rel_path: str, patterns) -> bool:
    """Gitignore-like matcher for task-relative POSIX paths.

    - "data/"      a directory with that name, at any depth, and everything under it
    - "*.pyc"      a wildcard without "/" matches the basename at any depth
    - "train.py"   a literal matches exactly that path (never "sub/train.py",
                   so an editable entry cannot leak to a same-named file elsewhere)
    - "src/*.py"   anything else is fnmatch'ed against the whole relative path

    The Claude Code hook duplicates this function (it must run without arh
    installed); tests/test_hooks.py keeps the two copies in agreement.
    """
    rel = rel_path.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            if ("/" + rel).find("/" + pattern) != -1:
                return True
        elif "/" not in pattern and any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatchcase(name, pattern):
                return True
        elif fnmatch.fnmatchcase(rel, pattern):
            return True
    return False


@dataclass(frozen=True)
class ConfirmSpec:
    """Optional holdout re-evaluation run before a new best is accepted."""

    command: str
    metric: str
    env: dict = field(default_factory=dict)
    tolerance: float = 0.0


@dataclass(frozen=True)
class TaskSpec:
    root: Path
    name: str
    description: str
    editable: tuple
    frozen: tuple
    ignore: tuple
    setup: str | None
    command: str
    budget_seconds: float
    metric: str
    direction: str  # "min" or "max"
    min_delta: float
    bounds: tuple  # (low, high); a metric outside is treated as a bug or a hack
    forbid_patterns: tuple
    integrity: tuple
    min_duration_fraction: float
    confirm: ConfirmSpec | None
    max_experiments: int | None
    program: str  # path of the research-direction prompt, relative to root

    # -- path policy -----------------------------------------------------
    def is_editable(self, rel: str) -> bool:
        return matches(rel, self.editable)

    def is_frozen(self, rel: str) -> bool:
        return matches(rel, self.frozen)

    def is_ignored(self, rel: str) -> bool:
        return matches(rel, self.ignore)

    # -- metric policy ---------------------------------------------------
    def is_better(self, new: float, best: float) -> bool:
        """Strict improvement by more than min_delta; ties are discarded,
        because an equal score never justifies extra code."""
        if self.direction == "min":
            return new < best - self.min_delta
        return new > best + self.min_delta

    def not_worse(self, new: float, best: float, tolerance: float) -> bool:
        if self.direction == "min":
            return new <= best + tolerance
        return new >= best - tolerance

    def expand(self, template: str) -> str:
        """`{python}` lets a task run with the interpreter arh itself runs in,
        so the venv that has numpy/torch is the one that trains."""
        return template.replace("{python}", _quote(sys.executable))


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def load_spec(task_dir: str | Path) -> TaskSpec:
    root = Path(task_dir).resolve()
    path = root / SPEC_FILE
    if not path.is_file():
        raise SpecError(f"no {SPEC_FILE} in {root}")
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"{path}: {exc}") from exc

    task = raw.get("task", {})
    files = raw.get("files", {})
    run = raw.get("run", {})
    metric = raw.get("metric", {})
    guards = raw.get("guards", {})
    loop = raw.get("loop", {})

    editable = tuple(files.get("editable", ()))
    frozen = tuple(files.get("frozen", ()))
    if not editable:
        raise SpecError("[files].editable must list at least one file")
    if not run.get("command"):
        raise SpecError("[run].command is required")
    if metric.get("direction", "min") not in ("min", "max"):
        raise SpecError("[metric].direction must be 'min' or 'max'")
    if not metric.get("name"):
        raise SpecError("[metric].name is required")

    overlap = [p for p in editable if matches(p, frozen)] + [p for p in frozen if matches(p, editable)]
    if overlap:
        raise SpecError(f"files cannot be both editable and frozen: {sorted(set(overlap))}")

    # TOML has inf, so "no upper bound" is written `bounds = [0.0, inf]`.
    bounds = guards.get("bounds", [-math.inf, math.inf])
    if len(bounds) != 2 or not float(bounds[0]) < float(bounds[1]):
        raise SpecError("[guards].bounds must be [low, high] with low < high")
    bounds = (float(bounds[0]), float(bounds[1]))

    confirm = None
    if "confirm" in raw:
        c = raw["confirm"]
        if not c.get("command") or not c.get("metric"):
            raise SpecError("[confirm] needs both command and metric")
        confirm = ConfirmSpec(
            command=c["command"],
            metric=c["metric"],
            env={str(k): str(v) for k, v in c.get("env", {}).items()},
            tolerance=float(c.get("tolerance", 0.0)),
        )

    spec = TaskSpec(
        root=root,
        name=task.get("name", root.name),
        description=task.get("description", ""),
        editable=editable,
        frozen=frozen,
        ignore=DEFAULT_IGNORE + tuple(files.get("ignore", ())),
        setup=run.get("setup"),
        command=run["command"],
        budget_seconds=float(run.get("budget_seconds", 600)),
        metric=metric["name"],
        direction=metric.get("direction", "min"),
        min_delta=float(metric.get("min_delta", 0.0)),
        bounds=bounds,
        forbid_patterns=tuple(guards.get("forbid_patterns", ())),
        integrity=tuple(guards.get("integrity", ())),
        min_duration_fraction=float(guards.get("min_duration_fraction", 0.0)),
        confirm=confirm,
        max_experiments=loop.get("max_experiments"),
        program=task.get("program", "program.md"),
    )

    missing = [p for p in editable + frozen if not any(True for _ in _glob(root, p))]
    if missing:
        raise SpecError(f"files listed in {SPEC_FILE} do not exist: {missing}")
    return spec


def _glob(root: Path, pattern: str):
    if any(ch in pattern for ch in "*?["):
        return root.glob(pattern)
    return [root / pattern] if (root / pattern).exists() else []
