"""The engine: evaluate the current edit, then keep it or revert it.

    arh run -m "what I changed"

      1. pre-run guards    allowlist, frozen/integrity hashes, forbidden patterns
      2. run               the task's command under a hard wall-clock budget
      3. post-run guards   the run itself must not have touched frozen files
      4. judge             crash? NaN? bounds? better than the best so far?
      5. confirm           optional holdout re-run before accepting a new best
      6. keep or revert    commit the editable files, or restore them from git
      7. ledger            append one row, whatever happened

The proposer (you, Claude Code, or `arh loop`) only ever edits files. Deciding
whether the edit counts is the engine's job, never the proposer's.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from arh import guards, runner
from arh.gitops import Git
from arh.ledger import Ledger
from arh.spec import STATE_DIR, TaskSpec, load_spec

SETUP_BUDGET_SECONDS = 900


class HarnessError(RuntimeError):
    """The harness refused to record an experiment (nothing was run)."""


class Harness:
    def __init__(self, task_dir: str | Path):
        self.spec: TaskSpec = load_spec(task_dir)
        self.root = self.spec.root
        self.state_dir = self.root / STATE_DIR
        self.ledger = Ledger(self.state_dir)
        self._state: dict | None = None

    # ------------------------------------------------------------------ state
    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def initialised(self) -> bool:
        return self.state_path.is_file()

    @property
    def state(self) -> dict:
        if self._state is None:
            if not self.initialised:
                raise HarnessError(f"{self.root} is not initialised; run `arh init {self.root}` first")
            self._state = json.loads(self.state_path.read_text())
        return self._state

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.state_path)  # atomic: a crash never leaves half a state file

    @property
    def git(self) -> Git:
        return Git(self.root, self.state["git_mode"])

    # ------------------------------------------------------------------- init
    @classmethod
    def init(cls, task_dir, tag: str | None = None, git_mode: str = "isolated", force: bool = False) -> "Harness":
        h = cls(task_dir)
        spec = h.spec
        if h.initialised:
            if not force:
                raise HarnessError(f"{h.state_dir} already exists; use --force to archive it and start over")
            h.state_dir.rename(h.root / f"{STATE_DIR}-old-{datetime.now():%Y%m%d-%H%M%S}")
        h.state_dir.mkdir(parents=True, exist_ok=True)

        if spec.setup:  # frozen data preparation, run once, outside any experiment
            result = runner.run_command(
                spec.expand(spec.setup), h.root, h.state_dir / "setup.log", SETUP_BUDGET_SECONDS
            )
            if result.timed_out or result.returncode != 0:
                raise HarnessError(f"setup failed; see {h.state_dir / 'setup.log'}:\n{result.tail(15)}")

        tag = tag or datetime.now().strftime("%b%d").lower()
        branch = f"autoresearch/{tag}"
        git = Git(h.root, git_mode)
        if git_mode == "isolated":
            git.init_isolated(branch, spec.ignore)
            git.run("add", "--all", "--", ".")
            git.run("commit", "--quiet", "--no-verify", "-m", f"arh: init task {spec.name}")
        else:
            if git.enclosing_repo() is None:
                raise HarnessError("--git-mode repo needs the task to be inside a git repository")
            tracked, _ = h._changes(git)
            if tracked:
                raise HarnessError(f"commit or stash these changes before init: {tracked}")
            git.create_branch(branch)
            _write_task_gitignore(h.root, spec.ignore)
            tracked, untracked = git.changed_files()
            paths = [p for p in tracked + untracked if not spec.is_ignored(p)]
            if paths:
                git.commit_paths(paths, f"arh: init task {spec.name}")

        h._state = {
            "task": spec.name,
            "tag": tag,
            "branch": branch,
            "git_mode": git_mode,
            "created": _now(),
            "init_commit": git.head(),
            "best": None,
            "baseline": None,
            # Stored resolved (not as patterns) so the Claude Code hook can
            # enforce them with nothing but the stdlib json module.
            "editable": list(spec.editable),
            "frozen": list(spec.frozen),
            "frozen_hashes": guards.hash_files(h.root, spec.frozen),
            "integrity_hashes": guards.hash_files(h.root, spec.integrity),
        }
        h.ledger.create()
        h._save_state()
        return h

    # ------------------------------------------------------------ experiments
    def baseline(self, stream: bool = False) -> dict:
        with self._lock():
            self._check_ready()
            if self.state["best"] is not None:
                raise HarnessError("baseline already recorded; use `arh run -m ...` for experiments")
            tracked, untracked = self._changes()
            if tracked or untracked:
                raise HarnessError(f"the baseline must run the committed code, but these files changed: {tracked + untracked}")
            return self._evaluate("baseline (unmodified code)", baseline=True, stream=stream)

    def run(self, description: str, stream: bool = False) -> dict:
        if not description.strip():
            raise HarnessError("describe the change: arh run -m \"what I changed and why\"")
        with self._lock():
            self._check_ready()
            if self.state["best"] is None:
                raise HarnessError("no baseline yet; run `arh baseline` first")
            limit = self.spec.max_experiments
            if limit is not None and self.ledger.next_id() > limit:
                raise HarnessError(f"max_experiments={limit} reached")
            tracked, untracked = self._changes()
            if not tracked and not untracked:
                raise HarnessError("nothing to evaluate: edit an editable file first")
            return self._evaluate(description, baseline=False, stream=stream)

    def _evaluate(self, description: str, baseline: bool, stream: bool) -> dict:
        spec, state = self.spec, self.state
        exp_id = self.ledger.next_id()
        runs = self.state_dir / "runs"
        runs.mkdir(exist_ok=True)
        tracked, untracked = self._changes()
        diff_text = self._diff(tracked, untracked)
        (runs / f"{exp_id:04d}.diff").write_text(diff_text)
        rec = {
            "id": exp_id,
            "timestamp": _now(),
            "description": description,
            "parent": self.git.head()[:7],
            "files": sorted(tracked + untracked),
            "best": state["best"]["metric"] if state["best"] else None,
            "metric": None,
            "delta": None,
            "commit": None,
            "duration_s": 0.0,
            "confirm_metric": None,
            "extra": {},
            "diff": f"{STATE_DIR}/runs/{exp_id:04d}.diff",
            "log": None,
        }

        # 1. pre-run guards: cheap, so they run before any compute is spent
        problems = (
            guards.check_allowlist(rec["files"], spec)
            + self._hash_problems()
            + guards.scan_diff(diff_text, spec.forbid_patterns)
        )
        if problems:
            return self._finish(rec, "invalid", "; ".join(problems))

        # 2. run the experiment
        result = runner.run_command(
            spec.expand(spec.command),
            cwd=self.root,
            log_path=runs / f"{exp_id:04d}.log",
            budget_seconds=spec.budget_seconds,
            env=self._run_env(exp_id, confirm=False),
            stream=stream,
        )
        rec["duration_s"] = round(result.duration, 2)
        rec["log"] = f"{STATE_DIR}/runs/{exp_id:04d}.log"
        rec["extra"] = {
            k: v[-1] for k, v in result.metrics.items() if k != spec.metric and guards.is_finite(v[-1])
        }

        # 3. post-run guards: the training code itself may have written to files
        tracked, untracked = self._changes()
        rec["files"] = sorted(tracked + untracked)
        problems = self._hash_problems() + guards.check_allowlist(rec["files"], spec)
        if problems:
            return self._finish(rec, "invalid", "during the run: " + "; ".join(problems))

        # 4. judge the reported metric
        status, reason, value = _judge(result, spec)
        rec["metric"] = value
        if status:
            return self._finish(rec, status, reason, tail=result.tail())
        if baseline:
            return self._confirm_then_keep(rec, reason="baseline")

        best = state["best"]["metric"]
        if not spec.is_better(value, best):
            return self._finish(rec, "discard", f"not better than best {best:.6g}")
        kept_durations = [r["duration_s"] for r in self.ledger.records() if r["status"] == "keep"]
        too_fast = guards.check_duration(result.duration, kept_durations, spec.min_duration_fraction)
        if too_fast:
            return self._finish(rec, "invalid", too_fast)
        return self._confirm_then_keep(rec, reason=f"improved on {best:.6g}")

    # 5. holdout confirmation, then 6. keep
    def _confirm_then_keep(self, rec: dict, reason: str) -> dict:
        spec, best = self.spec, self.state["best"]
        if spec.confirm is None:
            return self._finish(rec, "keep", reason)
        result = runner.run_command(
            spec.expand(spec.confirm.command),
            cwd=self.root,
            log_path=self.state_dir / "runs" / f"{rec['id']:04d}.confirm.log",
            budget_seconds=spec.budget_seconds,
            env=self._run_env(rec["id"], confirm=True),
        )
        values = result.metrics.get(spec.confirm.metric, [])
        if result.timed_out or result.returncode != 0 or len(values) != 1 or not guards.is_finite(values[0]):
            return self._finish(rec, "crash", "holdout confirmation run failed", tail=result.tail())
        rec["confirm_metric"] = values[0]
        if best is not None and not spec.not_worse(values[0], best["confirm_metric"], spec.confirm.tolerance):
            return self._finish(
                rec,
                "discard",
                f"val improved but holdout {spec.confirm.metric}={values[0]:.6g} is worse than "
                f"{best['confirm_metric']:.6g} (tolerance {spec.confirm.tolerance:g}): likely overfitting the val split",
            )
        return self._finish(rec, "keep", f"{reason}; holdout {spec.confirm.metric}={values[0]:.6g} confirmed")

    # 6. keep or revert, then 7. write the ledger
    def _finish(self, rec: dict, status: str, reason: str, tail: str = "") -> dict:
        state = self.state
        if rec["metric"] is not None and rec["best"] is not None:
            rec["delta"] = rec["metric"] - rec["best"]
        tracked, untracked = self._changes()
        if status == "keep":
            # Last look before anything is committed: the holdout run may have
            # touched files since the post-run check.
            late = self._hash_problems() + guards.check_allowlist(sorted(tracked + untracked), self.spec)
            if late:
                status, reason = "invalid", "before committing: " + "; ".join(late)
        rec["status"], rec["reason"] = status, reason
        if status == "keep":
            if tracked or untracked:
                message = f"{rec['description']}\n\narh experiment {rec['id']}: {self.spec.metric}={rec['metric']:.6g}"
                self.git.commit_paths(tracked + untracked, message)
            commit = self.git.head()
            rec["commit"] = commit[:7]
            state["best"] = {"id": rec["id"], "commit": commit, "metric": rec["metric"], "confirm_metric": rec["confirm_metric"]}
            if state["baseline"] is None:
                state["baseline"] = dict(state["best"])
        else:
            self._revert(tracked, untracked)
        self.ledger.append(rec)
        self._save_state()
        return {**rec, "tail": tail, "branch": state["branch"], "metric_name": self.spec.metric}

    def _revert(self, tracked: list[str], untracked: list[str]) -> None:
        """Back to the last kept commit. Tracked files (editable *and* frozen)
        come back from git; new files are deleted only if they fall under the
        editable patterns -- anything else is not ours to delete."""
        self.git.restore(tracked, "HEAD")
        for rel in untracked:
            if self.spec.is_editable(rel):
                (self.root / rel).unlink(missing_ok=True)

    # ------------------------------------------------------------- inspection
    def check(self) -> list[str]:
        """Every guard, right now, without running anything (`arh guard`)."""
        tracked, untracked = self._changes()
        problems = self._hash_problems()
        problems += guards.check_allowlist(sorted(tracked + untracked), self.spec)
        problems += guards.scan_diff(self._diff(tracked, untracked), self.spec.forbid_patterns)
        problems += self.ledger.check_consistency()
        try:
            self._check_ready()
        except HarnessError as exc:
            problems.append(str(exc))
        return problems

    def pending_diff(self) -> str:
        return self._diff(*self._changes())

    def summary(self) -> dict:
        records = self.ledger.records()
        counts = {s: sum(r["status"] == s for r in records) for s in ("keep", "discard", "crash", "invalid")}
        tracked, untracked = self._changes()
        return {
            "task": self.spec.name,
            "metric": self.spec.metric,
            "direction": self.spec.direction,
            "branch": self.state["branch"],
            "git_mode": self.state["git_mode"],
            "experiments": len(records),
            "counts": counts,
            "baseline": self.state["baseline"],
            "best": self.state["best"],
            "pending_changes": sorted(tracked + untracked),
            "max_experiments": self.spec.max_experiments,
            "recent": records[-10:],
        }

    # ---------------------------------------------------------------- helpers
    def _changes(self, git: Git | None = None) -> tuple[list[str], list[str]]:
        tracked, untracked = (git or self.git).changed_files()
        keep = lambda paths: sorted(p for p in paths if not self.spec.is_ignored(p))  # noqa: E731
        return keep(tracked), keep(untracked)

    def _diff(self, tracked: list[str], untracked: list[str]) -> str:
        text = self.git.diff(tracked)
        for rel in untracked:  # git diff does not show untracked files
            path = self.root / rel
            body = path.read_text(errors="replace") if path.is_file() else ""
            text += f"--- /dev/null\n+++ b/{rel}\n" + "".join(f"+{line}\n" for line in body.splitlines())
        return text

    def _hash_problems(self) -> list[str]:
        return guards.check_hashes(self.root, self.state["frozen_hashes"], self.spec.frozen, "frozen") + guards.check_hashes(
            self.root, self.state["integrity_hashes"], self.spec.integrity, "integrity"
        )

    def _check_ready(self) -> None:
        git, state = self.git, self.state
        if git.current_branch() != state["branch"]:
            raise HarnessError(f"expected branch {state['branch']}, but HEAD is on {git.current_branch()}")
        expected = state["best"]["commit"] if state["best"] else state["init_commit"]
        if git.head() != expected:
            raise HarnessError(
                f"HEAD moved to {git.head()[:7]} but the last kept commit is {expected[:7]}; "
                "only the harness may commit on this branch"
            )

    def _run_env(self, exp_id: int, confirm: bool) -> dict:
        env = {"ARH_EXPERIMENT_ID": str(exp_id), "ARH_BUDGET_SECONDS": str(self.spec.budget_seconds), "PYTHONHASHSEED": "0"}
        if self.spec.confirm:
            # Holdout switches are set only for the confirm run and actively
            # removed otherwise, so a stray shell variable cannot leak holdout.
            for key, value in self.spec.confirm.env.items():
                env[key] = value if confirm else None
        return env

    @contextmanager
    def _lock(self):
        """One experiment at a time per task, even across terminals/agents."""
        path = self.state_dir / "lock"
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                pid = int(path.read_text().strip() or 0)
                if pid and _alive(pid):
                    raise HarnessError(f"another arh process (pid {pid}) is running an experiment in this task")
                path.unlink(missing_ok=True)  # stale lock from a killed process
        else:
            raise HarnessError(f"could not acquire {path}")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _write_task_gitignore(root: Path, patterns) -> None:
    """In repo mode the harness's own state would otherwise show up as untracked
    noise in the user's `git status` -- and could be committed by accident."""
    path = root / ".gitignore"
    existing = path.read_text().splitlines() if path.is_file() else []
    missing = [p for p in patterns if p not in existing]
    if missing:
        header = [] if existing else ["# written by arh init: harness state and run artefacts"]
        path.write_text("\n".join(existing + header + list(missing)) + "\n")


def _judge(result: runner.RunResult, spec: TaskSpec) -> tuple[str | None, str, float | None]:
    """Turn a finished run into (status or None if valid, reason, metric)."""
    if result.timed_out:
        return "crash", f"timeout: killed after the {spec.budget_seconds:g}s budget", None
    if result.guard_failures:
        return "invalid", "evaluator refused to score: " + "; ".join(result.guard_failures), None
    if result.returncode != 0:
        return "crash", f"exit code {result.returncode}", None
    values = result.metrics.get(spec.metric, [])
    if not values:
        return "crash", f"no 'METRIC {spec.metric}=...' line in the output", None
    if len(values) > 1:
        return "invalid", f"{spec.metric} was reported {len(values)} times; only the frozen evaluator may report it, once", None
    value = values[0]
    if not guards.is_finite(value):
        return "crash", f"{spec.metric} is {value} (diverged?)", None
    out_of_bounds = guards.check_bounds(value, spec.bounds)
    if out_of_bounds:
        return "invalid", out_of_bounds, value
    return None, "", value


def format_verdict(v: dict) -> str:
    """The text a human or an agent reads after `arh run`."""
    name = v["metric_name"]
    head = f"experiment #{v['id']}: {v['status'].upper()}"
    if v["metric"] is not None:
        head += f"  {name}={v['metric']:.6g}"
    if v["best"] is not None and v["delta"] is not None:
        head += f"  (best was {v['best']:.6g}, delta {v['delta']:+.6g})"
    head += f"  [{v['duration_s']:.1f}s]"
    lines = [head, f"  reason: {v['reason']}"]
    if v["status"] == "keep":
        lines.append(f"  committed {v['commit']} on {v['branch']}")
    else:
        lines.append(f"  edits reverted to the last kept commit {v['parent']}")
    if v["log"]:
        lines.append(f"  log: {v['log']}")
    if v.get("tail") and v["status"] in ("crash", "invalid"):
        lines.append("  --- last lines of the log ---")
        lines.extend("  " + line for line in v["tail"].splitlines())
    return "\n".join(lines)


def find_task_dir(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) to the nearest autoresearch.toml."""
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "autoresearch.toml").is_file():
            return candidate
    raise HarnessError(f"no autoresearch.toml in {here} or its parents; pass -C <task_dir>")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
