"""The ledger is the loop's memory; the report is how a human reads it."""

import json

import pytest

from arh.ledger import TSV_COLUMNS, Ledger
from arh.report import render_markdown, write_report
from conftest import set_value


def record(**overrides):
    base = {
        "id": 0, "timestamp": "2026-09-19T10:00:00", "status": "keep", "metric": 1.0, "delta": None,
        "best": None, "commit": "abc1234", "parent": "0000000", "duration_s": 1.0,
        "description": "first", "reason": "baseline",
    }
    base.update(overrides)
    return base


def test_tsv_header_and_row(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.create()
    ledger.append(record())
    lines = (tmp_path / "results.tsv").read_text().splitlines()
    assert lines[0].split("\t") == list(TSV_COLUMNS)
    assert lines[1].split("\t")[:4] == ["0", "2026-09-19T10:00:00", "keep", "1.000000"]


def test_descriptions_cannot_break_the_grid(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.create()
    ledger.append(record(description="two\tcolumns\nand a newline"))
    assert len((tmp_path / "results.tsv").read_text().splitlines()) == 2
    assert len((tmp_path / "results.tsv").read_text().splitlines()[1].split("\t")) == len(TSV_COLUMNS)


def test_jsonl_keeps_everything(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.create()
    ledger.append(record(extra={"steps": 12.0}, reason="improved on 2"))
    stored = json.loads((tmp_path / "experiments.jsonl").read_text().strip())
    assert stored["extra"] == {"steps": 12.0} and stored["reason"] == "improved on 2"


def test_the_ledger_is_append_only(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.create()
    ledger.append(record())
    with pytest.raises(ValueError, match="append-only"):
        ledger.append(record(id=0))  # rewriting experiment 0 is not allowed
    with pytest.raises(ValueError, match="unknown status"):
        ledger.append(record(id=1, status="excellent"))


def test_consistency_check_notices_a_hand_edited_tsv(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.create()
    ledger.append(record())
    with open(tmp_path / "results.tsv", "a") as f:
        f.write("1\t2026-09-19T11:00:00\tkeep\t0.1\t-\t-\tdeadbee\tabc1234\t1.0\tinvented\n")
    assert ledger.check_consistency(), "a row with no matching jsonl record must be reported"


def test_report_writes_a_chart_and_a_readable_markdown(harness):
    set_value(harness.root, "4.0")
    harness.run("closer to the target")
    set_value(harness.root, "9.0")
    harness.run("much further away")

    png, md = write_report(harness)
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    text = md.read_text()
    assert "# autoresearch report: toy" in text
    assert "closer to the target" in text and "much further away" in text
    assert "Kept improvements" in text
    assert "baseline `2` -> best `1` (-50.0%)" in text


def test_markdown_survives_an_empty_ledger(harness):
    text = render_markdown([], harness, "progress.png")
    assert "nothing kept yet" in text
