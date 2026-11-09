# SPDX-License-Identifier: Apache-2.0
"""Checking a verdict, with one retry, then inconclusive (spec 012, FR-019; research R9)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.config import parse_config
from opscout.services.triage import Stores, begin, check_verdict, find_secrets
from tests.unit.triage.fakes import MemoryEvidence, MemoryRecords

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
CONFIG = parse_config(
    b"schema_version: 1\naws:\n  environments:\n    - {name: example-prod, account_id: '"
    b"123456789012', profile: example-prod, regions: [us-east-1]}\n",
    "config.yaml",
)
ALERT = "CRITICAL: errors in example-prod"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def opened() -> tuple[Stores, str, str]:
    used = Stores(evidence=MemoryEvidence(), records=MemoryRecords(), engine_version="0.0.0")
    run_id = begin(ALERT, None, CONFIG, NOW, used)["run_id"]
    metric = used.evidence.put(
        "read_metric",
        {"environment": "example-prod", "identity": None, "data": {"value": 52.0}},
        NOW + timedelta(seconds=10),
    )
    used.evidence.put("read_alarm", {"data": {}}, NOW + timedelta(seconds=11))
    return used, run_id, metric


def verdict(metric: str, quote: str = "52.0", **changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "classification": "real",
        "summary": "The metric stayed high.",
        "threshold": {
            "assessment": "keep",
            "reason": "Sustained.",
            "cites": [{"evidence": metric, "quote": quote}],
        },
        "claims": [{"text": "It was 52.", "cites": [{"evidence": metric, "quote": quote}]}],
        "timezone": "UTC",
        "alert_time_source": "invocation",
        "environment": "example-prod",
    }
    base.update(changes)
    return base


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


@spec("FR-019")
def test_a_pass_closes_the_run_as_checked() -> None:
    used, run_id, metric = opened()
    data = check_verdict(run_id, verdict(metric), later(60), used)
    assert (data["passed"], data["final"], data["outcome"], data["retry"]) == (
        True,
        True,
        "checked",
        False,
    )
    assert data["verdict"]["classification"] == "real"
    record = used.records.get(run_id)
    assert record is not None
    assert record.outcome == "checked"
    assert record.duration_seconds == 60
    assert record.ended_at == later(60)
    assert record.check.attempts == 1
    assert record.tools == {"read_alarm": 1, "read_metric": 1}


@spec("FR-019")
def test_one_retry_then_inconclusive() -> None:
    used, run_id, metric = opened()
    first = check_verdict(run_id, verdict(metric, "99.9"), later(30), used)
    assert (first["passed"], first["retry"], first["final"], first["outcome"]) == (
        False,
        True,
        False,
        "open",
    )
    failure = next(f for f in first["failures"] if f["where"] == "claims[0].cites[0]")
    assert failure["reason"] == "quote not found"
    assert "copy one value exactly" in failure["hint"]
    record = used.records.get(run_id)
    assert record is not None
    assert (record.outcome, record.check.attempts) == ("open", 1)

    second = check_verdict(run_id, verdict(metric, "98.7"), later(60), used)
    assert (second["passed"], second["retry"], second["final"], second["outcome"]) == (
        False,
        False,
        True,
        "inconclusive",
    )
    assert second["verdict"] is None
    record = used.records.get(run_id)
    assert record is not None
    assert (record.outcome, record.check.attempts) == ("inconclusive", 2)
    assert record.check.failures == second["failures"]

    with pytest.raises(ToolError) as refused:
        check_verdict(run_id, verdict(metric), later(90), used)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-019")
def test_a_retry_that_passes_closes_the_run_as_checked() -> None:
    used, run_id, metric = opened()
    check_verdict(run_id, verdict(metric, "99.9"), later(30), used)
    data = check_verdict(run_id, verdict(metric), later(40), used)
    assert (data["passed"], data["outcome"]) == (True, "checked")


@spec("FR-019")
def test_an_invalid_verdict_is_a_failed_attempt_with_the_validator_message() -> None:
    used, run_id, metric = opened()
    data = check_verdict(run_id, verdict(metric, classification="maybe"), later(30), used)
    assert data["retry"] is True
    assert data["failures"][0]["where"] == "classification"
    assert data["failures"][0]["reason"].startswith("invalid:")
    assert "maybe" not in str(data["failures"])


@spec("FR-019")
def test_an_unknown_run_is_refused() -> None:
    used, _, metric = opened()
    with pytest.raises(ToolError) as refused:
        check_verdict("20261106T120000Z-ffffff", verdict(metric), later(1), used)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-021")
def test_the_secret_finder_ignores_redaction_markers() -> None:
    assert find_secrets("DB_PASSWORD: [secret] and password=[credential]") == ()
    assert find_secrets("value 52.0 at 2026-11-06T09:00:00+00:00 in 123456789012") == ()
    assert find_secrets("postgres://u:p4ssw0rd@db.example.com/x") == ("connection-string",)
    assert find_secrets("key AKIAIOSFODNN7EXAMPLE") == ("credential",)


@spec("FR-021")
def test_a_verdict_holding_a_secret_is_refused_before_it_is_stored() -> None:
    used, run_id, metric = opened()
    leaky = verdict(metric, summary="Login with postgres://u:p4ssw0rd@db.example.com/x failed.")
    data = check_verdict(run_id, leaky, later(30), used)
    assert {"where": "summary", "reason": "secret-shaped value (connection-string)"} in data[
        "failures"
    ]
    record = used.records.get(run_id)
    assert record is not None
    assert "p4ssw0rd" not in record.model_dump_json()


@spec("FR-019")
def test_without_the_skeptic_a_checked_run_is_closed() -> None:
    used, run_id, metric = opened()
    check_verdict(run_id, verdict(metric), later(30), used)
    with pytest.raises(ToolError) as refused:
        check_verdict(run_id, verdict(metric), later(40), used)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-018")
def test_evidence_from_a_later_run_is_refused() -> None:
    used, run_id, _ = opened()
    begin(ALERT, None, CONFIG, NOW + timedelta(seconds=20), used)
    late = used.evidence.put(
        "read_metric", {"environment": "example-prod", "data": {"value": 77.0}}, later(25)
    )
    data = check_verdict(run_id, verdict(late, "77.0"), later(30), used)
    failure = next(f for f in data["failures"] if f["where"] == "claims[0].cites[0]")
    assert failure["reason"] == "evidence from another run"
