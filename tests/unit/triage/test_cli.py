# SPDX-License-Identifier: Apache-2.0
"""``opscout triage runs | show`` (spec 012, FR-026; contracts/cli.md)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from opscout.adapters.triage_files import FileRecords
from opscout.core.triage import Agreement, AlertRef, TriageRecord
from opscout.entrypoints.cli import main

NOW = datetime.now(UTC).replace(microsecond=0)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def record(hours_ago: float, suffix: str, **changes: object) -> TriageRecord:
    started = NOW - timedelta(hours=hours_ago)
    base = TriageRecord(
        run_id=f"{started:%Y%m%dT%H%M%SZ}-{suffix}",
        skill_version="0.0.0",
        engine_version="0.0.0",
        started_at=started,
        alert=AlertRef(
            format="example-notifier",
            environment="example-prod",
            resource="example-api-alb",
            digest=hashlib.sha256(b"alert").hexdigest(),
        ),
    )
    return base.model_copy(update=changes)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPSCOUT_DATA_DIR", str(tmp_path))
    store = FileRecords(tmp_path)
    store.write(record(30, "aaaaaa"))
    store.write(
        record(
            1,
            "bbbbbb",
            outcome="inconclusive",
            agreement=Agreement(answer="disagree", reason="noise", at=NOW),
        )
    )
    store.write(record(0.5, "cccccc"))
    return tmp_path


@spec("FR-026")
def test_runs_lists_the_newest_first(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["triage", "runs"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    rows = [line for line in lines if "example-notifier" in line]
    assert [row.split()[0][-6:] for row in rows] == ["cccccc", "bbbbbb", "aaaaaa"]
    assert "open" in rows[0]
    assert "inconclusive" in rows[1]
    assert "disagree" in rows[1]
    assert "abandoned" in rows[2]
    assert "example-prod" in rows[0]


@spec("FR-026")
def test_runs_honors_the_limit(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["triage", "runs", "--limit", "1"]) == 0
    assert capsys.readouterr().out.count("example-notifier") == 1
    assert main(["triage", "runs", "--limit", "0"]) == 2


@spec("FR-026")
def test_show_prints_one_record(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = record(1, "bbbbbb").run_id
    assert main(["triage", "show", run_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["run_id"] == run_id
    assert shown["agreement"]["answer"] == "disagree"
    assert main(["triage", "show", "20261106T000000Z-ffffff"]) == 1


@spec("FR-026")
def test_an_unreadable_record_does_not_stop_the_listing(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data / "triage" / "runs" / "29991231T000000Z-ffffff.json").write_text("{", encoding="utf-8")
    assert main(["triage", "runs"]) == 0
    out = capsys.readouterr().out
    assert "29991231T000000Z-ffffff.json" in out
    assert out.count("example-notifier") == 3


@spec("FR-026")
def test_no_runs_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_DATA_DIR", str(tmp_path))
    assert main(["triage", "runs"]) == 0
    assert "no triage runs" in capsys.readouterr().out
