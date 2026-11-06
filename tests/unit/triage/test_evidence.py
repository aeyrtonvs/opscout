# SPDX-License-Identifier: Apache-2.0
"""The evidence store (spec 012, FR-007; research R2)."""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from opscout.adapters.evidence_files import FileEvidence
from opscout.core.triage import EvidenceStore
from tests.unit.triage.fakes import MemoryEvidence

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
RESULT = {"environment": "example-prod", "data": {"value": 52.0, "time": "09:40"}}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


@pytest.fixture(params=["files", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> EvidenceStore:
    factories: dict[str, Callable[[], EvidenceStore]] = {
        "files": lambda: FileEvidence(tmp_path),
        "memory": MemoryEvidence,
    }
    return factories[request.param]()


@spec("FR-007")
def test_identifiers_have_their_shape_and_are_unique(store: EvidenceStore) -> None:
    ids = {store.put("read_metric", RESULT, NOW) for _ in range(2_000)}
    assert len(ids) == 2_000
    assert all(re.fullmatch(r"ev-[0-9a-f]{10}", evidence) for evidence in ids)


@spec("FR-007")
def test_a_result_round_trips(store: EvidenceStore) -> None:
    evidence = store.put("read_metric", RESULT, NOW)
    stored = store.get(evidence)
    assert stored is not None
    assert (stored.id, stored.tool, stored.stored_at, dict(stored.result)) == (
        evidence,
        "read_metric",
        NOW,
        RESULT,
    )
    assert store.get("ev-ffffffffff") is None


@spec("FR-007")
def test_since_and_prune(store: EvidenceStore) -> None:
    old = store.put("read_alarm", RESULT, NOW - timedelta(hours=25))
    recent = store.put("read_metric", RESULT, NOW)
    assert [item.id for item in store.since(NOW - timedelta(minutes=1))] == [recent]
    store.prune(NOW - timedelta(hours=24))
    assert store.get(old) is None
    assert store.get(recent) is not None


@spec("FR-007")
def test_the_files_live_under_the_data_directory(tmp_path: Path) -> None:
    evidence = FileEvidence(tmp_path).put("read_metric", RESULT, NOW)
    path = tmp_path / "triage" / "evidence" / f"{evidence}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["tool"] == "read_metric"


@spec("FR-007")
def test_an_unreadable_file_is_skipped(tmp_path: Path) -> None:
    store = FileEvidence(tmp_path)
    good = store.put("read_metric", RESULT, NOW)
    broken = tmp_path / "triage" / "evidence" / "ev-0000000000.json"
    broken.write_text("{not json", encoding="utf-8")
    assert store.get("ev-0000000000") is None
    assert [item.id for item in store.since(NOW - timedelta(hours=1))] == [good]
    store.prune(NOW + timedelta(hours=1))
    assert store.get(good) is None


@spec("FR-007")
def test_a_malformed_identifier_reads_nothing(tmp_path: Path) -> None:
    store = FileEvidence(tmp_path)
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    assert store.get("../../secret") is None
