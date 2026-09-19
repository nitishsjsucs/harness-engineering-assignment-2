"""Append-only experiment ledger.

Two files, written together for every experiment:

    results.tsv         one line per experiment; easy to eyeball, grep, paste
    experiments.jsonl   the same record plus everything else (reason, extra
                        metrics, holdout score, log path); what tools read

The ledger is the loop's long-term memory. A fresh agent (or a fresh context
window) can resume from it alone, so nothing here is ever rewritten.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

TSV_COLUMNS = ("id", "timestamp", "status", "metric", "delta", "best", "commit", "parent", "duration_s", "description")
STATUSES = ("keep", "discard", "crash", "invalid")


class Ledger:
    def __init__(self, state_dir: Path):
        self.tsv = Path(state_dir) / "results.tsv"
        self.jsonl = Path(state_dir) / "experiments.jsonl"

    def create(self) -> None:
        if self.tsv.exists() or self.jsonl.exists():
            raise FileExistsError(f"ledger already exists in {self.tsv.parent}")
        self.tsv.write_text("\t".join(TSV_COLUMNS) + "\n")
        self.jsonl.write_text("")

    def append(self, record: dict) -> None:
        if record["status"] not in STATUSES:
            raise ValueError(f"unknown status {record['status']!r}")
        if record["id"] != self.next_id():
            raise ValueError(f"ledger is append-only: expected id {self.next_id()}, got {record['id']}")
        row = [_fmt(record.get(col)) for col in TSV_COLUMNS]
        # "a" mode: we can only ever add to the end of the file.
        with open(self.tsv, "a") as f:
            f.write("\t".join(row) + "\n")
        with open(self.jsonl, "a") as f:
            f.write(json.dumps(record, sort_keys=True, allow_nan=False, default=_json_default) + "\n")

    def records(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        return [json.loads(line) for line in self.jsonl.read_text().splitlines() if line.strip()]

    def next_id(self) -> int:
        return len(self.records())

    def check_consistency(self) -> list[str]:
        """Both files must describe the same experiments in the same order."""
        problems = []
        records = self.records()
        rows = self.tsv.read_text().splitlines()[1:] if self.tsv.exists() else []
        if len(rows) != len(records):
            problems.append(f"results.tsv has {len(rows)} rows but experiments.jsonl has {len(records)}")
        for i, rec in enumerate(records):
            if rec.get("id") != i:
                problems.append(f"experiments.jsonl line {i + 1} has id {rec.get('id')}, expected {i}")
        return problems


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return "nan" if math.isnan(value) else f"{value:.6f}"
    # Tabs or newlines inside a description would corrupt the TSV grid.
    return " ".join(str(value).split())


def _json_default(value):
    raise TypeError(f"not JSON serialisable: {value!r}")
