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
    """Turn raw (x, y) coordinates into model inputs.
    Add quadratic features (x^2, y^2, x*y) plus bias to allow simple non-linear
    decision boundaries while keeping the model still linear in parameters.

    Also add polar-coordinate features: radius r and angle theta (as sin
    and cos) so the model can more naturally represent spiral structure.
    """
    x = X[:, 0:1]
    y = X[:, 1:2]
    x2 = x * x
    y2 = y * y
    xy = x * y
    # radius
    r = np.sqrt(x2 + y2)
    # angle theta; use sin and cos of theta to avoid discontinuities
    # arctan2 is fine but we represent angle by sin/cos which are continuous
    # in Cartesian coordinates when combined with r.
    theta = np.arctan2(y, x)
    sin_t = np.sin(theta)
    cos_t = np.cos(theta)
    return np.hstack([x, y, x2, y2, xy, r, sin_t, cos_t, np.ones((len(X), 1))])


def softmax(scores):
    scores = scores - scores.max(axis=1, keepdims=True)  # stable: exp of <= 0
    exp = np.exp(scores)
    return exp / exp.sum(axis=1, keepdims=True)


def train():
    X, y = training_data()
    features = featurize(X)
    targets = np.eye(CLASSES)[y]

    rng = np.random.default_rng(SEED)
    # Small one-hidden-layer MLP: features -> hidden (tanh) -> logits -> softmax.
    HIDDEN = 16
    W1 = rng.normal(0, 0.1, size=(features.shape[1], HIDDEN))
    W2 = rng.normal(0, 0.1, size=(HIDDEN, CLASSES))
    # Momentum buffers for SGD with momentum
    MOMENTUM = 0.9
    vW1 = np.zeros_like(W1)
    vW2 = np.zeros_like(W2)

    steps = 0
    start = time.time()
    while time.time() - start < TIME_BUDGET:
        # forward
        hidden_lin = features @ W1
        hidden = np.tanh(hidden_lin)
        logits = hidden @ W2
        probs = softmax(logits)

        # loss gradient w.r.t. logits
        ds = (probs - targets) / len(features)
        # gradients
        grad_W2 = hidden.T @ ds
        dh = ds @ W2.T
        grad_W1 = features.T @ (dh * (1 - hidden * hidden))

        # parameter update (SGD with momentum)
        vW1 = MOMENTUM * vW1 + LEARNING_RATE * grad_W1
        vW2 = MOMENTUM * vW2 + LEARNING_RATE * grad_W2
        W1 -= vW1
        W2 -= vW2

        steps += 1
        if steps % 2000 == 0:
            train_loss = -np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None)))
            print(f"step {steps}: train_loss {train_loss:.4f}")

    def predict_proba(features_in):
        f = featurize(features_in)
        h = np.tanh(f @ W1)
        return softmax(h @ W2)

    return predict_proba, steps


if __name__ == "__main__":
    predict_proba, steps = train()
    report(predict_proba, steps=steps)
