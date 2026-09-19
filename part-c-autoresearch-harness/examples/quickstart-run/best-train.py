"""EDITABLE. The only file an experiment may change in the quickstart task.

One hidden layer with tanh units, trained with full-batch gradient descent for
TIME_BUDGET seconds. A linear model cannot bend around a spiral; this can.

Rules that the harness enforces anyway: never print a METRIC line yourself
(prepare.report does that), never touch prepare.py, and never reach for the
val or holdout split.
"""

import time

import numpy as np

from prepare import TIME_BUDGET, report, training_data

SEED = 0
LEARNING_RATE = 0.5
HIDDEN = 64
CLASSES = 3


def featurize(X):
    """Turn raw (x, y) coordinates into model inputs. A bias column is the
    minimum; better features are one of the obvious things to try."""
    radius = np.sqrt((X ** 2).sum(axis=1, keepdims=True))
    angle = np.arctan2(X[:, :1], X[:, 1:2])
    return np.hstack([X, radius, np.sin(angle), np.cos(angle), radius * np.sin(3 * angle), radius * np.cos(3 * angle), np.ones((len(X), 1))])


def softmax(scores):
    scores = scores - scores.max(axis=1, keepdims=True)  # stable: exp of <= 0
    exp = np.exp(scores)
    return exp / exp.sum(axis=1, keepdims=True)


def forward(features, params):
    W1, b1, W2, b2 = params
    hidden = np.tanh(features @ W1 + b1)
    return hidden, softmax(hidden @ W2 + b2)


def train():
    X, y = training_data()
    features = featurize(X)
    targets = np.eye(CLASSES)[y]

    rng = np.random.default_rng(SEED)
    params = [
        rng.normal(0, 0.5, size=(features.shape[1], HIDDEN)),
        np.zeros(HIDDEN),
        rng.normal(0, 0.5, size=(HIDDEN, CLASSES)),
        np.zeros(CLASSES),
    ]

    steps = 0
    start = time.time()
    while time.time() - start < TIME_BUDGET:
        hidden, probs = forward(features, params)
        d_scores = (probs - targets) / len(features)
        d_hidden = (d_scores @ params[2].T) * (1 - hidden ** 2)  # tanh'
        grads = [features.T @ d_hidden, d_hidden.sum(0), hidden.T @ d_scores, d_scores.sum(0)]
        for param, grad in zip(params, grads):
            param -= LEARNING_RATE * grad
        steps += 1
        if steps % 2000 == 0:
            train_loss = -np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None)))
            print(f"step {steps}: train_loss {train_loss:.4f}")

    def predict_proba(features_in):
        return forward(featurize(features_in), params)[1]

    return predict_proba, steps


if __name__ == "__main__":
    predict_proba, steps = train()
    report(predict_proba, steps=steps)
