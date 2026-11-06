# SPDX-License-Identifier: Apache-2.0
"""The skeptic pass: its evidence, its one revision, its setting (spec 012, FR-029; R9, R13)."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.services.config import parse_config
from opscout.services.tools.runtime import run_tool
from opscout.services.triage import Stores, begin, check_verdict
from tests.unit.mcp.fakes import FakeGateway, tool_context
from tests.unit.triage.fakes import MemoryEvidence, MemoryRecords

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
CONFIG = parse_config(
    b"schema_version: 1\naws:\n  environments:\n    - {name: example-prod, account_id: '"
    b"123456789012', profile: example-prod, regions: [us-east-1]}\ntriage:\n  skeptic: true\n",
    "config.yaml",
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def checked_run() -> tuple[Stores, str, str]:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    run_id = begin("CRITICAL: example-prod", None, CONFIG, NOW, stores)["run_id"]
    metric = stores.evidence.put(
        "read_metric", {"environment": "example-prod", "data": {"value": 52.0}}, NOW
    )
    assert check_verdict(run_id, verdict(metric), NOW + timedelta(seconds=30), stores)["passed"]
    return stores, run_id, metric


def verdict(metric: str, classification: str = "real", quote: str = "52.0") -> dict[str, Any]:
    return {
        "classification": classification,
        "summary": "The metric stayed high.",
        "threshold": {"assessment": "not-assessable", "reason": "One point only."},
        "claims": [{"text": "It was 52.", "cites": [{"evidence": metric, "quote": quote}]}],
        "timezone": "UTC",
        "alert_time_source": "invocation",
        "environment": "example-prod",
    }


@spec("FR-029")
def test_show_evidence_returns_stored_results_and_stores_nothing_new() -> None:
    store = MemoryEvidence()
    kept = store.put("read_metric", {"data": {"value": 52.0}}, NOW)
    context = dataclasses.replace(tool_context(FakeGateway()), evidence=store)
    failed, result = run_tool("show_evidence", {"ids": [kept, "ev-ffffffffff"]}, context)
    assert not failed
    assert [item["id"] for item in result["data"]["items"]] == [kept]
    assert result["data"]["items"][0]["result"] == {"data": {"value": 52.0}}
    assert result["data"]["missing"] == ["ev-ffffffffff"]
    assert result["evidence"] is None
    assert len(store.items) == 1
    failed, result = run_tool("show_evidence", {"ids": []}, context)
    assert failed


@spec("FR-029")
def test_a_passing_revision_replaces_the_verdict() -> None:
    stores, run_id, metric = checked_run()
    revised = verdict(metric, "false-positive")
    revised["skeptic"] = {"ran": True, "disagreed": True, "note": "One point is a spike."}
    data = check_verdict(run_id, revised, NOW + timedelta(seconds=60), stores)
    assert (data["passed"], data["outcome"]) == (True, "checked")
    assert data["verdict"]["classification"] == "false-positive"
    record = stores.records.get(run_id)
    assert record is not None
    assert record.revised is True
    assert record.verdict is not None
    assert record.verdict.skeptic.disagreed is True


@spec("FR-029")
def test_a_failing_revision_keeps_the_earlier_verdict() -> None:
    stores, run_id, metric = checked_run()
    data = check_verdict(run_id, verdict(metric, "false-positive", "99.9"), NOW, stores)
    assert data["passed"] is False
    assert data["outcome"] == "checked"
    assert data["verdict"]["classification"] == "real"
    record = stores.records.get(run_id)
    assert record is not None
    assert record.revised is False
    assert record.check.failures


@spec("FR-029")
def test_a_second_revision_is_refused() -> None:
    stores, run_id, metric = checked_run()
    check_verdict(run_id, verdict(metric), NOW, stores)
    with pytest.raises(ToolError) as refused:
        check_verdict(run_id, verdict(metric), NOW, stores)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-029")
def test_begin_returns_the_skeptic_setting() -> None:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    assert begin("x", None, CONFIG, NOW, stores)["settings"]["skeptic"] is True
    bare = parse_config(b"schema_version: 1\n", "config.yaml")
    assert begin("x", None, bare, NOW, stores)["settings"]["skeptic"] is False
