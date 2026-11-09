# SPDX-License-Identifier: Apache-2.0
"""The triage record store (spec 012, FR-025; research R8)."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from opscout.adapters.triage_files import FileRecords
from opscout.core.triage import AlertRef, TriageRecord, TriageStore, Unreadable
from tests.unit.triage.fakes import MemoryRecords

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
ALERT_TEXT = "CRITICAL: example-api 5XX errors above threshold"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def record(minutes: int, suffix: str = "a1b2c3") -> TriageRecord:
    started = NOW + timedelta(minutes=minutes)
    return TriageRecord(
        run_id=f"{started:%Y%m%dT%H%M%SZ}-{suffix}",
        skill_version="0.0.0",
        engine_version="0.0.0",
        started_at=started,
        alert=AlertRef(
            format="example-notifier",
            environment="example-prod",
            resource="example-api-alb",
            digest=hashlib.sha256(ALERT_TEXT.encode()).hexdigest(),
        ),
    )


@pytest.fixture(params=["files", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> TriageStore:
    factories: dict[str, Callable[[], TriageStore]] = {
        "files": lambda: FileRecords(tmp_path),
        "memory": MemoryRecords,
    }
    return factories[request.param]()


@spec("FR-025")
def test_a_record_round_trips_and_is_replaced(store: TriageStore) -> None:
    first = record(0)
    store.write(first)
    assert store.get(first.run_id) == first
    closed = first.model_copy(update={"outcome": "inconclusive"})
    store.write(closed)
    assert store.get(first.run_id) == closed
    assert store.get("20261106T000000Z-ffffff") is None


@spec("FR-025")
def test_records_are_listed_newest_first(store: TriageStore) -> None:
    for minutes in (0, 5, 2):
        store.write(record(minutes, f"{minutes:06d}"))
    listed = store.records(2)
    assert [r.run_id for r in listed if isinstance(r, TriageRecord)] == [
        record(5, "000005").run_id,
        record(2, "000002").run_id,
    ]


@spec("FR-025")
def test_the_file_is_where_the_plan_says(tmp_path: Path) -> None:
    FileRecords(tmp_path).write(record(0))
    path = tmp_path / "triage" / "runs" / f"{record(0).run_id}.json"
    text = path.read_text(encoding="utf-8")
    assert ALERT_TEXT not in text
    assert hashlib.sha256(ALERT_TEXT.encode()).hexdigest() in text


@spec("FR-025")
def test_an_unreadable_record_is_listed_by_name(tmp_path: Path) -> None:
    store = FileRecords(tmp_path)
    store.write(record(0))
    broken = tmp_path / "triage" / "runs" / "20261106T110000Z-ffffff.json"
    broken.write_text("{", encoding="utf-8")
    listed = store.records(10)
    assert listed[0] == Unreadable("20261106T110000Z-ffffff.json")
    assert isinstance(listed[1], TriageRecord)
    assert store.get("20261106T110000Z-ffffff") is None


@spec("FR-025")
def test_a_malformed_run_id_reads_nothing(tmp_path: Path) -> None:
    assert FileRecords(tmp_path).get("../../etc/passwd") is None


@spec("FR-025")
def test_a_record_names_its_skill_and_version() -> None:
    from opscout.services.triage import Stores, begin
    from tests.unit.triage.fakes import MemoryEvidence

    stores = Stores(MemoryEvidence(), MemoryRecords(), "1.2.3")
    run_id = begin(ALERT_TEXT, None, None, NOW, stores)["run_id"]
    found = stores.records.get(run_id)
    assert found is not None
    assert (found.skill, found.skill_version, found.engine_version) == (
        "alert-triage",
        "1.2.3",
        "1.2.3",
    )
