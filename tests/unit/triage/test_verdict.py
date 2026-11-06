# SPDX-License-Identifier: Apache-2.0
"""The verdict and its check (spec 012, FR-017, FR-018, FR-021; contracts/verdict.md)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from opscout.core.triage import StoredEvidence, Verdict, check

STARTED = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
METRIC = "ev-0000000001"
CHANGE = "ev-0000000002"
OLD = "ev-0000000003"
OTHER_ENV = "ev-0000000004"

EVIDENCE = {
    METRIC: StoredEvidence(
        id=METRIC,
        tool="read_metric",
        stored_at=STARTED + timedelta(seconds=5),
        result={
            "environment": "example-prod",
            "identity": "reference identity",
            "timezone": "UTC",
            "data": {
                "metric": "HTTPCode_Target_5XX_Count",
                "datapoints": [
                    {"time": "2026-11-06T09:35:00+00:00", "value": 50.5},
                    {"time": "2026-11-06T09:40:00+00:00", "value": 52.0},
                ],
                "note": "errors   rose  sharply",
            },
        },
    ),
    CHANGE: StoredEvidence(
        id=CHANGE,
        tool="recent_changes",
        stored_at=STARTED + timedelta(seconds=6),
        result={
            "environment": "example-prod",
            "identity": "reference identity",
            "data": {"changes": [{"action": "UpdateService", "actor": "deployer"}]},
        },
    ),
    OLD: StoredEvidence(
        id=OLD,
        tool="read_metric",
        stored_at=STARTED - timedelta(minutes=1),
        result={"environment": "example-prod", "data": {"value": 7}},
    ),
    OTHER_ENV: StoredEvidence(
        id=OTHER_ENV,
        tool="read_alarm",
        stored_at=STARTED + timedelta(seconds=7),
        result={
            "environment": "example-dev",
            "identity": "own identity, not verified",
            "data": {"alarm": "example-dev-alarm"},
        },
    ),
}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def cite(evidence: str, quote: str) -> dict[str, str]:
    return {"evidence": evidence, "quote": quote}


def verdict(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "classification": "real",
        "summary": "Sustained 5XX errors after a deployment.",
        "cause": {"text": "The deployment started it.", "cites": [cite(CHANGE, "UpdateService")]},
        "threshold": {
            "assessment": "keep",
            "proposal": None,
            "reason": "Crossed for 40 minutes.",
            "cites": [cite(METRIC, "52.0")],
        },
        "claims": [{"text": "5XX rose above 50.", "cites": [cite(METRIC, "50.5")]}],
        "assumptions": ["The invocation time was used."],
        "timezone": "UTC",
        "alert_timezone": None,
        "alert_time_source": "invocation",
        "environment": "example-prod",
        "identity": "reference identity",
        "missing": [],
        "skeptic": {"ran": False, "disagreed": False, "note": None},
    }
    base.update(changes)
    return base


def no_secrets(_: str) -> Sequence[str]:
    return ()


def run(data: dict[str, Any], find_secrets: Any = no_secrets) -> list[tuple[str, str]]:
    result = check(Verdict.model_validate(data), EVIDENCE.get, STARTED, find_secrets)
    assert result.passed == (result.failures == ())
    return [(failure.where, failure.reason) for failure in result.failures]


@spec("FR-017")
def test_a_supported_verdict_passes() -> None:
    assert run(verdict()) == []


@spec("FR-017")
@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"colour": "red"}, "an unknown key"),
        ({"classification": "maybe"}, "an unknown classification"),
        ({"summary": ""}, "an empty summary"),
        ({"summary": "x" * 301}, "a summary over 300 characters"),
        (
            {"threshold": {"assessment": "tune", "proposal": None, "reason": "r", "cites": []}},
            "tune without a proposal",
        ),
        (
            {"threshold": {"assessment": "keep", "proposal": "80", "reason": "r", "cites": []}},
            "a proposal without tune",
        ),
        ({"timezone": "Mars/Base"}, "an unknown timezone"),
        ({"alert_timezone": "Nowhere"}, "an unknown alert timezone"),
        ({"alert_time_source": "guess"}, "an unknown time source"),
        ({"missing": ["metrics", "metrics"]}, "a kind listed twice"),
        ({"missing": ["weather"]}, "an unknown evidence kind"),
        ({"claims": [{"text": "x", "cites": []}]}, "a claim with no citation"),
        (
            {
                "claims": [
                    {
                        "text": "x",
                        "cites": [{"evidence": METRIC, "observability": "t", "quote": "q"}],
                    }
                ]
            },
            "a citation that is both kinds",
        ),
        ({"claims": [{"text": "x", "cites": [cite("ev-1", "q")]}]}, "a malformed evidence id"),
        ({"claims": [{"text": "x", "cites": [cite(METRIC, "")]}]}, "an empty quote"),
        ({"claims": [{"text": "x", "cites": [cite(METRIC, "q" * 301)]}]}, "a long quote"),
        ({"claims": [{"text": "c", "cites": [cite(METRIC, "50.5")]}] * 21}, "21 claims"),
    ],
)
def test_the_schema_refuses(changes: dict[str, Any], why: str) -> None:
    with pytest.raises(ValidationError):
        Verdict.model_validate(verdict(**changes))


@spec("FR-018")
def test_unknown_evidence_and_evidence_from_another_run_fail() -> None:
    claims = [
        {"text": "a", "cites": [cite(METRIC, "50.5")]},
        {"text": "b", "cites": [cite("ev-ffffffffff", "50.5")]},
        {"text": "c", "cites": [cite(OLD, "7")]},
    ]
    assert run(verdict(claims=claims)) == [
        ("claims[1].cites[0]", "unknown evidence"),
        ("claims[2].cites[0]", "evidence from another run"),
    ]


@spec("FR-018")
@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("HTTPCode_Target_5XX_Count", True),
        ("Target_5XX", True),
        ("errors rose sharply", True),  # whitespace collapsed on both sides
        ("52", True),  # a number by value: 52 == 52.0
        ("52.00", True),
        ("50.5", True),
        ("09:35:00", True),
        ("datapoints", False),  # a field name is not a value
        ("metric", False),
        ("53", False),
        ("5", False),  # under 3 characters: must equal a whole scalar
        ("rose sharply indeed", False),
        ('"value": 52.0', True),  # a key-and-value fragment as the model saw it
        ('{"time":"2026-11-06T09:40:00+00:00","value":52.0}', True),
        ('"metric":"HTTPCode_Target_5XX_Count"', True),
        ('"value": 53.0', False),
        ('"datapoints"', False),  # a key with no value is not a quote
        ('"datapoints":', False),
        ('"datapoints":[', False),  # a key with a nested value is not a quote (review H1)
        ('"partial": false', False),  # the envelope never counts (review H1)
        ('"timezone":"UTC"', False),
        ("example-prod", False),  # the envelope's environment is not data
        ("6T09", False),  # cuts a number on both sides
        ("T09", False),  # under four characters: a whole value only
        ("rose", True),  # a whole word
        ("ros", False),
    ],
)
def test_a_quote_must_appear_in_one_value_of_its_result(quote: str, found: bool) -> None:
    failures = run(verdict(claims=[{"text": "t", "cites": [cite(METRIC, quote)]}]))
    assert (failures == []) is found, failures


@spec("FR-018")
def test_a_short_quote_equal_to_a_whole_value_passes() -> None:
    evidence = {
        METRIC: StoredEvidence(
            id=METRIC, tool="read_alarm", stored_at=STARTED, result={"data": {"state": "OK"}}
        )
    }
    data = verdict(
        cause=None,
        threshold={"assessment": "not-assessable", "proposal": None, "reason": "r", "cites": []},
        claims=[{"text": "t", "cites": [cite(METRIC, "OK")]}],
        environment=None,
        identity=None,
    )
    assert check(Verdict.model_validate(data), evidence.get, STARTED, no_secrets).passed


@spec("FR-018")
def test_a_classification_resting_only_on_unchecked_evidence_fails() -> None:
    unchecked = {"observability": "search_traces", "quote": "timeout in checkout"}
    data = verdict(claims=[{"text": "Traces show timeouts.", "cites": [unchecked]}])
    assert ("classification", "no checked support for the classification") in run(data)
    data = verdict(classification="false-positive", claims=[{"text": "t", "cites": [unchecked]}])
    assert ("classification", "no checked support for the classification") in run(data)


@spec("FR-018")
def test_a_cause_or_assessment_resting_only_on_unchecked_evidence_fails() -> None:
    unchecked = {"observability": "get_metrics", "quote": "p99 3s"}
    data = verdict(
        cause={"text": "Slow upstream.", "cites": [unchecked]},
        threshold={"assessment": "tune", "proposal": "80", "reason": "r", "cites": [unchecked]},
    )
    failures = run(data)
    assert ("cause", "no checked support for the cause") in failures
    assert ("threshold", "no checked support for the threshold assessment") in failures


@spec("FR-018")
def test_checked_and_unchecked_together_pass() -> None:
    unchecked = {"observability": "search_traces", "quote": "timeout"}
    data = verdict(claims=[{"text": "t", "cites": [cite(METRIC, "50.5"), unchecked]}])
    assert run(data) == []


@spec("FR-018")
def test_an_inconclusive_verdict_needs_no_citation() -> None:
    data = verdict(
        classification="inconclusive",
        cause=None,
        threshold={"assessment": "not-assessable", "proposal": None, "reason": "r", "cites": []},
        claims=[],
        environment=None,
        identity=None,
    )
    assert run(data) == []


@spec("FR-018")
def test_a_failing_citation_does_not_count_as_support() -> None:
    data = verdict(claims=[{"text": "t", "cites": [cite(METRIC, "99.9")]}])
    assert run(data) == [
        ("claims[0].cites[0]", "quote not found"),
        ("classification", "no checked support for the classification"),
    ]


@spec("FR-018")
def test_the_environment_must_match_the_evidence() -> None:
    data = verdict(
        claims=[
            {"text": "t", "cites": [cite(METRIC, "50.5")]},
            {"text": "u", "cites": [cite(OTHER_ENV, "example-dev-alarm")]},
        ]
    )
    failures = run(data)
    assert ("environment", "environment differs from the evidence") in failures
    assert ("identity", "identity differs from the evidence") in failures


@spec("FR-021")
def test_a_secret_shaped_value_fails_without_being_repeated() -> None:
    def finder(text: str) -> Sequence[str]:
        return ("credential",) if "AKIA" in text else ()

    data = verdict(assumptions=["the key AKIAIOSFODNN7EXAMPLE was rotated"])
    failures = run(data, finder)
    assert failures == [("assumptions[0]", "secret-shaped value (credential)")]
    assert "AKIA" not in repr(failures)


@spec("FR-018")
def test_evidence_that_cannot_be_cited_fails() -> None:
    echo = "ev-0000000005"
    evidence = {
        **EVIDENCE,
        echo: StoredEvidence(
            id=echo,
            tool="resolve_environment",
            stored_at=STARTED + timedelta(seconds=1),
            result={"data": {"unmatched": [{"value": "the deploy broke it"}]}},
            citable=False,
        ),
    }
    data = verdict(
        cause={"text": "The deploy broke it.", "cites": [cite(echo, "the deploy broke it")]}
    )
    result = check(Verdict.model_validate(data), evidence.get, STARTED, no_secrets)
    assert ("cause.cites[0]", "evidence that cannot be cited") in [
        (f.where, f.reason) for f in result.failures
    ]


@spec("FR-018")
def test_evidence_stored_after_the_next_run_began_is_not_this_runs() -> None:
    later_run = STARTED + timedelta(seconds=5, microseconds=500)
    result = check(
        Verdict.model_validate(verdict()), EVIDENCE.get, STARTED, no_secrets, until=later_run
    )
    assert ("cause.cites[0]", "evidence from another run") in [
        (f.where, f.reason) for f in result.failures
    ]


@spec("FR-018")
def test_the_verdict_environment_must_be_the_runs() -> None:
    data = verdict(
        claims=[{"text": "t", "cites": [cite(METRIC, "50.5")]}],
        cause=None,
        environment="example-dev",
        identity=None,
    )
    data["threshold"]["cites"] = [cite(METRIC, "52.0")]
    result = check(
        Verdict.model_validate(data),
        EVIDENCE.get,
        STARTED,
        no_secrets,
        run_environment="example-prod",
    )
    assert ("environment", "environment differs from the run's") in [
        (f.where, f.reason) for f in result.failures
    ]


@spec("FR-018")
def test_a_number_with_an_underscore_is_not_a_number() -> None:
    evidence = {
        METRIC: StoredEvidence(
            id=METRIC, tool="read_metric", stored_at=STARTED, result={"data": {"v": "1_0"}}
        )
    }
    data = verdict(
        cause=None,
        threshold={"assessment": "not-assessable", "proposal": None, "reason": "r", "cites": []},
        claims=[{"text": "t", "cites": [cite(METRIC, "10")]}],
        environment=None,
        identity=None,
    )
    assert not check(Verdict.model_validate(data), evidence.get, STARTED, no_secrets).passed
