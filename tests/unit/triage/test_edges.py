# SPDX-License-Identifier: Apache-2.0
"""The triage tools' remaining edges, each a refusal or a rule (spec 012)."""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opscout.core.tools import ErrorReason, ToolError
from opscout.core.triage import quote_found
from opscout.services import iac
from opscout.services.config import parse_config
from opscout.services.tools.runtime import run_tool
from opscout.services.triage import Stores, begin, check_verdict
from tests.unit.mcp.fakes import ENVIRONMENTS, FakeGateway, tool_context
from tests.unit.triage.fakes import MemoryEvidence, MemoryFiles, MemoryRecords

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
CLONES = parse_config(
    b"schema_version: 1\ntriage:\n  infrastructure:\n    - {name: example-infra, path: /srv/x}\n",
    "config.yaml",
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


@spec("FR-018")
@pytest.mark.parametrize(
    ("quote", "result", "found"),
    [
        ("   ", {"data": {"v": "x"}}, False),
        ("value", {"environment": "example-prod"}, False),  # no data at all
        ("true", {"data": {"gone": None, "healthy": True}}, True),
        ("false", {"data": {"healthy": True}}, False),
        ("52", {"data": {"v": "52.00"}}, True),  # a number written as text
    ],
)
def test_quote_edges(quote: str, result: dict[str, Any], found: bool) -> None:
    assert quote_found(quote, result) is found


@spec("FR-013")
def test_without_a_file_reader_the_tools_say_so() -> None:
    calls: list[Callable[[], object]] = [
        lambda: iac.search(CLONES, None, "x1", environment=None, clone=None),
        lambda: iac.read(CLONES, None, "example-infra/a.tf", 1, 2),
    ]
    for call in calls:
        with pytest.raises(ToolError) as refused:
            call()
        assert refused.value.reason is ErrorReason.NOT_CONFIGURED


@spec("FR-013")
def test_the_match_cap_holds_across_files_and_binary_code_is_skipped() -> None:
    files = MemoryFiles(
        roots={
            "/srv/x": {
                "a.tf": "match\n" * 30,
                "b.tf": "match\n" * 30,
                "c.tf": "match\n",
                "0blob.tf": b"\x00match",
            }
        }
    )
    data = iac.search(CLONES, files, "match", environment=None, clone=None)
    assert len(data["matches"]) == 50
    assert data["more"] is True
    assert {m["path"] for m in data["matches"]} == {"example-infra/a.tf", "example-infra/b.tf"}


@spec("FR-006")
def test_the_triage_tools_refuse_without_their_stores_or_with_bad_input() -> None:
    context = tool_context(FakeGateway(), config=ENVIRONMENTS)
    failed, result = run_tool("begin_triage", {"text": "x"}, context)
    assert failed
    assert result["error"]["reason"] == "not-configured"
    failed, result = run_tool("show_evidence", {"ids": ["ev-0000000000"]}, context)
    assert failed
    assert result["error"]["reason"] == "not-configured"
    stored = dataclasses.replace(context, evidence=MemoryEvidence(), records=MemoryRecords())
    failed, result = run_tool("check_verdict", {"run_id": "r", "verdict": "nope"}, stored)
    assert result["error"]["reason"] == "invalid-input"
    failed, result = run_tool("read_iac", {"path": "a/b.tf", "start": "1", "end": 2}, stored)
    assert result["error"]["reason"] == "invalid-input"
    failed, result = run_tool("begin_triage", {"text": "nothing matches"}, stored)
    assert not failed
    assert result["environment"] is None


@spec("FR-008")
@pytest.mark.parametrize("named", ["yesterday", "2026-11-06T09:00:00"])
def test_a_named_time_must_be_iso_with_an_offset(named: str) -> None:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    with pytest.raises(ToolError) as refused:
        begin("x", named, None, NOW, stores)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-025")
def test_the_record_names_cited_platform_tools_and_counts_only_the_runs_calls() -> None:
    stores = Stores(MemoryEvidence(), MemoryRecords(), "0.0.0")
    run_id = begin("x", None, None, NOW, stores)["run_id"]
    metric = stores.evidence.put("read_metric", {"data": {"value": 52.0}}, NOW)
    stores.evidence.put("read_alarm", {"data": {}}, NOW + timedelta(hours=1))
    verdict = {
        "classification": "real",
        "summary": "s",
        "cause": {
            "text": "Slow upstream.",
            "cites": [
                {"evidence": metric, "quote": "52.0"},
                {"observability": "search_traces", "quote": "timeout"},
            ],
        },
        "threshold": {"assessment": "not-assessable", "reason": "r"},
        "claims": [{"text": "c", "cites": [{"evidence": metric, "quote": "52.0"}]}],
        "timezone": "UTC",
        "alert_time_source": "invocation",
    }
    assert check_verdict(run_id, verdict, NOW + timedelta(minutes=1), stores)["passed"]
    record = stores.records.get(run_id)
    assert record is not None
    assert record.observability_tools == ["search_traces"]
    assert record.tools == {"read_metric": 1}
