"""FROZEN. Data preparation and evaluation for the tinygpt task.

`python prepare.py` downloads tiny-shakespeare, checks its hash, builds the
character vocabulary and writes the train/val token arrays. The harness runs
this once, at `arh init`, and then hashes both this file and the data files it
produced -- an experiment that changes either is rejected.

The evaluator here owns the score end to end:

  * it picks the evaluation slice (train.py never sees it),
  * it feeds the model inputs only, never targets,
  * it computes the cross-entropy itself, in bits per byte,
  * it checks that the model is deterministic and causal before trusting it,
  * and it prints the one METRIC line the harness reads.

Bits per byte (rather than per token) follows Karpathy's autoresearch, where it
keeps scores comparable across tokenizers. Here the vocabulary is fixed, so it
is simply a readable unit: how many bits the model spends per character.
"""

import hashlib
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

HERE = Path(__file__).parent
DATA = HERE / "data"
MIRRORS = [
    "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt",
    "https://raw.githubusercontent.com/jcjohnson/torch-rnn/master/data/tiny-shakespeare.txt",
]
SHA256 = "86c4e6aa9db7c042ec79f339dcb96d42b0075e16b8fc2e86bf0ca57e2dc565ed"

TIME_BUDGET = 60.0  # seconds of training per experiment -- frozen, so it cannot be bought
CONTEXT = 256  # evaluation context length; the model must accept sequences this long
EVAL_CHARS = 50_000  # fixed held-out slice, identical for every experiment
EVAL_BATCH = 16
VAL_FRACTION = 0.1


class LeakError(RuntimeError):
    """The model broke a rule of the evaluation (not causal, wrong shape, ...)."""


class DivergedError(RuntimeError):
    """The model produced NaN or inf: a broken idea, not a broken rule."""


# --------------------------------------------------------------- preparation
def download() -> str:
    DATA.mkdir(exist_ok=True)
    raw = DATA / "input.txt"
    if raw.is_file() and _sha256(raw) == SHA256:
        return raw.read_text()
    cached = os.environ.get("TINYSHAKESPEARE_PATH")  # offline escape hatch
    sources = ([cached] if cached else []) + MIRRORS
    for source in sources:
        try:
            if source == cached:
                text = Path(source).read_text()
            else:
                print(f"downloading {source}")
                with urllib.request.urlopen(source, timeout=30) as response:
                    text = response.read().decode("utf-8")
        except Exception as exc:  # try the next mirror
            print(f"  failed: {exc.__class__.__name__}: {exc}")
            continue
        raw.write_text(text)
        if _sha256(raw) != SHA256:
            print(f"  wrong checksum from {source}, trying the next source")
            continue
        return text
    raise SystemExit(
        "could not fetch tiny-shakespeare. Download input.txt by hand into "
        f"{DATA}, or point TINYSHAKESPEARE_PATH at a local copy."
    )


def prepare() -> None:
    text = download()
    vocab = sorted(set(text))
    stoi = {ch: i for i, ch in enumerate(vocab)}
    tokens = np.array([stoi[ch] for ch in text], dtype=np.uint16)
    split = int(len(tokens) * (1 - VAL_FRACTION))
    np.save(DATA / "train.npy", tokens[:split])
    np.save(DATA / "val.npy", tokens[split:])
    (DATA / "meta.json").write_text(json.dumps({"vocab": vocab, "vocab_size": len(vocab)}))
    print(f"{len(text)} characters, vocab {len(vocab)}, train {split}, val {len(tokens) - split}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------- loading
def load_meta() -> dict:
    return json.loads((DATA / "meta.json").read_text())


def load_train_tokens() -> np.ndarray:
    """The only tokens train.py is supposed to touch."""
    return np.load(DATA / "train.npy")


def _eval_tokens() -> np.ndarray:
    """Private: the held-out slice. `val` is the front of the val split and
    `holdout` is the back, so an optional confirm run scores on characters that
    were never used to select anything."""
    tokens = np.load(DATA / "val.npy")
    if os.environ.get("ARH_EVAL_SPLIT") == "holdout":
        return tokens[-(EVAL_CHARS + 1):]
    return tokens[: EVAL_CHARS + 1]


# ---------------------------------------------------------------- evaluation
@torch.no_grad()
def evaluate_bpb(forward, device="cpu"):
    """Score `forward` (a callable mapping (B, T) token ids to (B, T, V) logits).

    Returns (metric_name, bits_per_byte).
    """
    split = "holdout" if os.environ.get("ARH_EVAL_SPLIT") == "holdout" else "val"
    tokens = _eval_tokens()
    meta = load_meta()
    vocab_size = meta["vocab_size"]
    byte_len = np.array([len(ch.encode("utf-8")) for ch in meta["vocab"]], dtype=np.int64)

    windows = (len(tokens) - 1) // CONTEXT
    inputs = tokens[: windows * CONTEXT].reshape(windows, CONTEXT).astype(np.int64)
    targets = tokens[1 : windows * CONTEXT + 1].reshape(windows, CONTEXT).astype(np.int64)

    _check_causal(forward, torch.from_numpy(inputs[:2]).to(device), vocab_size)

    total_nats, total_bytes = 0.0, 0
    for start in range(0, windows, EVAL_BATCH):
        x = torch.from_numpy(inputs[start : start + EVAL_BATCH]).to(device)
        y = torch.from_numpy(targets[start : start + EVAL_BATCH]).to(device)
        logits = _logits(forward, x, vocab_size)
        loss = F.cross_entropy(logits.reshape(-1, vocab_size), y.reshape(-1), reduction="sum")
        total_nats += float(loss.item())
        total_bytes += int(byte_len[targets[start : start + EVAL_BATCH]].sum())
    if not math.isfinite(total_nats):
        raise DivergedError("the model produced NaN or inf logits")
    return f"{split}_bpb", total_nats / (math.log(2) * total_bytes)


def _logits(forward, x, vocab_size):
    out = forward(x)
    if not torch.is_tensor(out) or out.shape != (x.shape[0], x.shape[1], vocab_size):
        raise LeakError(f"forward returned {getattr(out, 'shape', type(out))}, expected {(x.shape[0], x.shape[1], vocab_size)}")
    return out.float()


def _check_causal(forward, x, vocab_size):
    """Two cheap probes that catch the two ways this score gets faked.

    1. determinism: the same input must give the same logits, otherwise the
       model is still in training mode (dropout) and the score is noise.
    2. causality: rewriting the second half of the input must not change the
       logits in the first half. A model that peeks at the next token scores
       near zero bits per byte, which looks like a breakthrough and is not.
    """
    first = _logits(forward, x, vocab_size)
    if not torch.allclose(first, _logits(forward, x, vocab_size), atol=1e-5):
        raise LeakError("forward is not deterministic; put the model in eval() mode (dropout off)")
    cut = x.shape[1] // 2
    perturbed = x.clone()
    generator = torch.Generator(device="cpu").manual_seed(0)
    noise = torch.randint(0, vocab_size, perturbed[:, cut:].shape, generator=generator).to(x.device)
    perturbed[:, cut:] = noise
    after = _logits(forward, perturbed, vocab_size)
    if not torch.allclose(first[:, :cut], after[:, :cut], atol=1e-4):
        raise LeakError("the model attends to future tokens; the evaluation only scores causal models")


def report(forward, device="cpu", **extra):
    """The single source of METRIC lines for this task."""
    try:
        name, bpb = evaluate_bpb(forward, device)
    except DivergedError as exc:
        print(f"training diverged: {exc}")
        sys.exit(1)
    except LeakError as exc:
        print(f"GUARD_FAIL {exc}")
        sys.exit(1)
    pairs = " ".join(f"{k}={v}" for k, v in extra.items())
    print(f"METRIC {name}={bpb:.6f} {pairs}".strip())


if __name__ == "__main__":
    prepare()
