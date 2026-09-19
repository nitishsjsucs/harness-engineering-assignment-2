"""EDITABLE. A small character-level GPT, trained for TIME_BUDGET seconds.

This is the file an experiment changes: architecture, optimiser, schedule,
batch shape, initialisation, anything. It ends by handing the frozen evaluator
a callable, which scores it and prints the METRIC line.

Device: MPS on Apple Silicon, CUDA if present, CPU otherwise. Everything here
is sized so that one experiment fits in about a minute on a laptop.
"""

import time

import numpy as np
import torch
import torch.nn as nn
from torch.nn import functional as F

from prepare import CONTEXT, TIME_BUDGET, load_meta, load_train_tokens, report

SEED = 1337
BLOCK = CONTEXT  # train on the same window length the evaluator scores
BATCH = 32
N_LAYER = 4
N_HEAD = 4
N_EMBD = 128
LEARNING_RATE = 1e-3


def pick_device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class CausalSelfAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.qkv = nn.Linear(N_EMBD, 3 * N_EMBD)
        self.proj = nn.Linear(N_EMBD, N_EMBD)

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.qkv(x).split(N_EMBD, dim=2)
        # (B, heads, T, head_dim)
        q, k, v = (t.view(B, T, N_HEAD, C // N_HEAD).transpose(1, 2) for t in (q, k, v))
        # is_causal=True is what keeps the evaluator's causality probe happy:
        # position t may only look at positions <= t.
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.proj(y.transpose(1, 2).contiguous().view(B, T, C))


class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.ln1 = nn.LayerNorm(N_EMBD)
        self.attn = CausalSelfAttention()
        self.ln2 = nn.LayerNorm(N_EMBD)
        self.mlp = nn.Sequential(nn.Linear(N_EMBD, 4 * N_EMBD), nn.GELU(), nn.Linear(4 * N_EMBD, N_EMBD))

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        return x + self.mlp(self.ln2(x))


class GPT(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.tok = nn.Embedding(vocab_size, N_EMBD)
        # CONTEXT positions, because the evaluator scores 256-token windows
        self.pos = nn.Embedding(CONTEXT, N_EMBD)
        self.blocks = nn.ModuleList(Block() for _ in range(N_LAYER))
        self.ln_f = nn.LayerNorm(N_EMBD)
        self.head = nn.Linear(N_EMBD, vocab_size, bias=False)

    def forward(self, idx):
        positions = torch.arange(idx.shape[1], device=idx.device)
        x = self.tok(idx) + self.pos(positions)
        for block in self.blocks:
            x = block(x)
        return self.head(self.ln_f(x))


def get_batch(tokens, device, generator):
    starts = torch.randint(len(tokens) - BLOCK - 1, (BATCH,), generator=generator)
    x = np.stack([tokens[s : s + BLOCK] for s in starts.tolist()]).astype(np.int64)
    y = np.stack([tokens[s + 1 : s + BLOCK + 1] for s in starts.tolist()]).astype(np.int64)
    return torch.from_numpy(x).to(device), torch.from_numpy(y).to(device)


def main():
    torch.manual_seed(SEED)
    device = pick_device()
    tokens = load_train_tokens()
    vocab_size = load_meta()["vocab_size"]

    model = GPT(vocab_size).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    generator = torch.Generator().manual_seed(SEED)
    params_m = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"device {device}, {params_m:.2f}M parameters, training for {TIME_BUDGET:g}s")

    steps = 0
    start = time.time()
    while time.time() - start < TIME_BUDGET:
        x, y = get_batch(tokens, device, generator)
        loss = F.cross_entropy(model(x).view(-1, vocab_size), y.view(-1))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        steps += 1
        if steps % 100 == 0:
            print(f"step {steps}: train_loss {loss.item():.4f} ({time.time() - start:.0f}s)")

    model.eval()  # the evaluator refuses a model whose forward is not deterministic
    report(model, device=device, steps=steps, params_m=round(params_m, 3))


if __name__ == "__main__":
    main()
