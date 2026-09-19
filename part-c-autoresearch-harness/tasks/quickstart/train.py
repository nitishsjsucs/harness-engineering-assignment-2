"""EDITABLE. The only file an experiment may change in the quickstart task.

Baseline: multinomial logistic regression trained with full-batch gradient
descent for TIME_BUDGET seconds. It is deliberately weak -- a linear model
cannot separate spirals -- so there is plenty to improve.

Rules that the harness enforces anyway: never print a METRIC line yourself
(prepare.report does that), never touch prepare.py, and never reach for the
val or holdout split.
"""

import time

import numpy as np

from prepare import TIME_BUDGET, report, training_data

SEED = 0
LEARNING_RATE = 0.05
CLASSES = 3


def featurize(X):
    """Turn raw (x, y) coordinates into model inputs. A bias column is the
    minimum; better features are one of the obvious things to try."""
    return np.hstack([X, np.ones((len(X), 1))])


def softmax(scores):
    scores = scores - scores.max(axis=1, keepdims=True)  # stable: exp of <= 0
    exp = np.exp(scores)
    return exp / exp.sum(axis=1, keepdims=True)


def train():
    X, y = training_data()
    features = featurize(X)
    targets = np.eye(CLASSES)[y]

    rng = np.random.default_rng(SEED)
    weights = rng.normal(0, 0.01, size=(features.shape[1], CLASSES))

    steps = 0
    start = time.time()
    while time.time() - start < TIME_BUDGET:
        probs = softmax(features @ weights)
        gradient = features.T @ (probs - targets) / len(features)
        weights -= LEARNING_RATE * gradient
        steps += 1
        if steps % 2000 == 0:
            train_loss = -np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None)))
            print(f"step {steps}: train_loss {train_loss:.4f}")

    def predict_proba(features_in):
        return softmax(featurize(features_in) @ weights)

    return predict_proba, steps


if __name__ == "__main__":
    predict_proba, steps = train()
    report(predict_proba, steps=steps)
