# SPDX-License-Identifier: Apache-2.0
"""Recording the user's agreement (spec 012, FR-022, FR-024; research R11)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.config import parse_config
from opscout.services.triage import Stores, begin, check_verdict, record_agreement
from tests.unit.triage.fakes import MemoryEvidence, MemoryRecords

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
CONFIG = parse_config(b"schema_version: 1\n", "config.yaml")
INCONCLUSIVE = {
    "classification": "inconclusive",
    "summary": "Nothing could be read.",
    "threshold": {"assessment": "not-assessable", "reason": "AWS is not configured."},
    "timezone": "UTC",
    "alert_time_source": "invocation",
}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def closed_run() -> tuple[Stores, str]:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    run_id = begin("CRITICAL: x", None, CONFIG, NOW, stores)["run_id"]
    assert check_verdict(run_id, INCONCLUSIVE, NOW + timedelta(seconds=5), stores)["passed"]
    return stores, run_id


@spec("FR-024")
@pytest.mark.parametrize(
    ("answer", "reason"),
    [("agree", None), ("disagree", "It was a planned load test."), ("not-answered", None)],
)
def test_each_answer_is_stored(answer: str, reason: str | None) -> None:
    stores, run_id = closed_run()
    data = record_agreement(run_id, answer, reason, NOW + timedelta(minutes=1), stores)
    assert data["agreement"]["answer"] == answer
    record = stores.records.get(run_id)
    assert record is not None
    assert record.agreement is not None
    assert (record.agreement.answer, record.agreement.reason) == (answer, reason)
    assert record.agreement.at == NOW + timedelta(minutes=1)


@spec("FR-024")
def test_a_second_answer_replaces_the_first() -> None:
    stores, run_id = closed_run()
    record_agreement(run_id, "agree", None, NOW, stores)
    record_agreement(run_id, "disagree", "On second thought.", NOW, stores)
    record = stores.records.get(run_id)
    assert record is not None
    assert record.agreement is not None
    assert record.agreement.answer == "disagree"


@spec("FR-024")
def test_an_open_run_or_a_bad_answer_is_refused() -> None:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    run_id = begin("CRITICAL: x", None, CONFIG, NOW, stores)["run_id"]
    calls: list[Callable[[], object]] = [
        lambda: record_agreement(run_id, "agree", None, NOW, stores),
        lambda: record_agreement("20261106T120000Z-ffffff", "agree", None, NOW, stores),
    ]
    for call in calls:
        with pytest.raises(ToolError) as refused:
            call()
        assert refused.value.reason is ErrorReason.INVALID_INPUT
    stores, run_id = closed_run()
    for answer, reason in (("maybe", None), ("disagree", "x" * 501)):
        with pytest.raises(ToolError):
            record_agreement(run_id, answer, reason, NOW, stores)


@spec("FR-024")
def test_a_reason_is_redacted_before_it_is_stored() -> None:
    stores, run_id = closed_run()
    record_agreement(run_id, "disagree", "key AKIAIOSFODNN7EXAMPLE leaked", NOW, stores)
    record = stores.records.get(run_id)
    assert record is not None
    assert "AKIA" not in record.model_dump_json()


@spec("FR-022")
def test_without_writeups_the_built_in_ticket_format_is_returned() -> None:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    data = begin("CRITICAL: x", None, None, NOW, stores)
    assert data["ticket_format"]["origin"] == "built-in"
    assert data["ticket_format"]["sections"][0] == "What happened"
