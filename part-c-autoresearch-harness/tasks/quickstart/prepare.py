"""FROZEN. Data and evaluation for the quickstart task -- the harness hashes
this file and rejects any experiment that changes it.

Everything that defines the score lives here: the dataset, the split, the loss,
the sanity checks on the model's output, and the only line in the task that is
allowed to print a METRIC. train.py may use `training_data()` and `report()`
and nothing else.

Task: 3-class spiral classification, 3600 points, deterministic.
Metric: mean cross-entropy (nats) on the val split -- lower is better.
"""

import os
import sys

import numpy as np

SEED = 1337
CLASSES = 3
PER_CLASS = 1200
TIME_BUDGET = 3.0  # seconds of training per experiment; frozen so it cannot be bought
SPLITS = {"train": (0.0, 0.6), "val": (0.6, 0.8), "holdout": (0.8, 1.0)}


def _dataset():
    """Two-dimensional spirals: linearly inseparable, so the baseline has a lot
    of room, and deterministic, so two runs of the same code score the same."""
    rng = np.random.default_rng(SEED)
    xs, ys = [], []
    for label in range(CLASSES):
        t = np.linspace(0.0, 1.0, PER_CLASS)
        radius = 4.0 * t
        theta = t * 5.0 + label * (2 * np.pi / CLASSES) + rng.normal(0, 0.25, PER_CLASS)
        xs.append(np.stack([radius * np.sin(theta), radius * np.cos(theta)], axis=1))
        ys.append(np.full(PER_CLASS, label))
    X = np.concatenate(xs).astype(np.float64)
    y = np.concatenate(ys).astype(np.int64)
    order = rng.permutation(len(X))  # shuffle once, so the splits are class-balanced
    return X[order], y[order]


def _split(name):
    """Private on purpose: training code that reaches for a split by name is
    reaching for the val or holdout labels. The task's forbid_patterns guard
    rejects any diff that adds a call to it."""
    X, y = _dataset()
    lo, hi = SPLITS[name]
    start, stop = int(lo * len(X)), int(hi * len(X))
    return X[start:stop], y[start:stop]


def training_data():
    """The only data train.py is supposed to touch."""
    return _split("train")


class DivergedError(RuntimeError):
    """The training run produced NaN or inf: a broken idea, not a broken rule."""


def evaluate(predict_proba):
    """Score a model. The model never sees the labels: it is handed features
    and must return per-class probabilities.

    Returns (metric_name, cross_entropy). Raises ValueError if the returned
    array is not a probability distribution -- silently clipping a malformed
    output into a good-looking score is exactly how fake progress happens.
    """
    split = "holdout" if os.environ.get("ARH_EVAL_SPLIT") == "holdout" else "val"
    X, y = _split(split)
    probs = np.asarray(predict_proba(X), dtype=np.float64)
    if probs.shape != (len(X), CLASSES):
        raise ValueError(f"predict_proba returned {probs.shape}, expected {(len(X), CLASSES)}")
    if not np.all(np.isfinite(probs)):
        raise DivergedError("predictions contain NaN or inf")
    if probs.min() < 0 or not np.allclose(probs.sum(axis=1), 1.0, atol=1e-3):
        raise ValueError("predict_proba must return rows that are non-negative and sum to 1")
    loss = float(-np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None))))
    return f"{split}_loss", loss


def report(predict_proba, **extra):
    """The single source of METRIC lines for this task.

    Two different failures, two different verdicts: a diverged run exits
    non-zero (the harness records a crash), a rule violation prints GUARD_FAIL
    (the harness records the experiment as invalid).
    """
    try:
        name, loss = evaluate(predict_proba)
    except DivergedError as exc:
        print(f"training diverged: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(f"GUARD_FAIL {exc}")
        sys.exit(1)
    pairs = " ".join(f"{k}={v}" for k, v in extra.items())
    print(f"METRIC {name}={loss:.6f} {pairs}".strip())


if __name__ == "__main__":  # `python prepare.py` prints a description of the data
    X, y = _dataset()
    print(f"{len(X)} points, {CLASSES} classes, splits: " + ", ".join(f"{k} {len(_split(k)[0])}" for k in SPLITS))
