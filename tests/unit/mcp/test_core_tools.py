# SPDX-License-Identifier: Apache-2.0
"""Windows, caps, the size cap, envelopes and errors (spec 011, FR-004, FR-011, FR-013)."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from opscout.core.tools import (
    CAP_CEILINGS,
    CAP_DEFAULTS,
    Capped,
    Caps,
    Envelope,
    ErrorReason,
    ToolError,
    Window,
    fit,
    parse_window,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def window(**given: str) -> tuple[Window, Capped | None]:
    return parse_window(
        given.get("since"),
        given.get("until"),
        given.get("last"),
        now=NOW,
        default=timedelta(hours=1),
        maximum=DAY,
        cap="log_window_hours",
    )


@spec("FR-011")
def test_a_window_takes_since_until_or_last_and_defaults() -> None:
    assert window() == (Window(NOW - timedelta(hours=1), NOW), None)
    assert window(last="15m")[0] == Window(NOW - timedelta(minutes=15), NOW)
    assert window(last="3h")[0].start == NOW - timedelta(hours=3)
    since = window(since="2026-11-06T04:00:00-06:00", until="2026-11-06T05:00:00-06:00")[0]
    assert since == Window(
        datetime(2026, 11, 6, 10, 0, tzinfo=UTC), datetime(2026, 11, 6, 11, 0, tzinfo=UTC)
    )


@spec("FR-011")
@pytest.mark.parametrize(
    "given",
    [
        {"since": "2026-11-06T11:00:00Z", "until": "2026-11-06T10:00:00Z"},
        {"since": "2026-11-06T11:00:00Z", "until": "2026-11-06T11:00:00Z"},
        {"until": "2026-11-06T12:06:00Z"},
        {"since": "2026-11-06T10:00:00"},
        {"last": "3w"},
        {"last": "0h"},
        {"since": "2026-11-06T10:00:00Z", "last": "1h"},
        {"since": "yesterday"},
    ],
)
def test_a_bad_window_is_refused(given: dict[str, str]) -> None:
    with pytest.raises(ToolError) as error:
        window(**given)
    assert error.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-011")
def test_a_window_past_its_maximum_is_capped_and_recorded() -> None:
    capped_window, capped = window(last="3d")
    assert capped_window == Window(NOW - DAY, NOW)
    assert capped == Capped("log_window_hours", 24, 2 * 24 * 60)


@spec("FR-011")
def test_caps_default_to_the_table_and_the_configuration_only_lowers_them() -> None:
    caps = Caps.from_config({})
    assert caps.limit("log_rows") == CAP_CEILINGS["log_rows"] == 1000
    assert caps.default("log_rows") == CAP_DEFAULTS["log_rows"] == 100
    lowered = Caps.from_config({"log_rows": 50})
    assert (lowered.limit("log_rows"), lowered.default("log_rows")) == (50, 50)
    with pytest.raises(ValueError, match="at most 1000"):
        Caps.from_config({"log_rows": 1001})
    with pytest.raises(ValueError, match="unknown cap"):
        Caps.from_config({"rows": 5})
    assert set(CAP_DEFAULTS) == set(CAP_CEILINGS)
    assert all(CAP_DEFAULTS[name] <= CAP_CEILINGS[name] for name in CAP_CEILINGS)


@spec("FR-011")
def test_an_oversized_result_drops_whole_items_from_the_end() -> None:
    data = {"rows": [{"message": f"row {index} " + "x" * 90} for index in range(100)]}

    fitted, capped = fit(data, 2_000)

    assert len(json.dumps(fitted)) <= 2_000
    assert fitted["rows"] == data["rows"][: len(fitted["rows"])]
    assert capped == [Capped("result_chars", 2_000, 100 - len(fitted["rows"]))]
    assert fit({"rows": [1, 2]}, 2_000) == ({"rows": [1, 2]}, [])


@spec("FR-011")
def test_one_huge_string_is_cut_before_items_are_dropped() -> None:
    fitted, capped = fit({"rows": [{"message": "y" * 50_000}]}, 40_000)

    message = fitted["rows"][0]["message"]
    assert message.startswith("y" * 100)
    assert message.endswith("[cut 46000 characters]")
    assert len(json.dumps(fitted)) <= 40_000
    assert [entry.cap for entry in capped] == ["string_chars"]


@spec("FR-013")
def test_an_envelope_renders_every_time_in_its_timezone_with_an_offset() -> None:
    zone = ZoneInfo("Europe/Lisbon")
    envelope = Envelope(
        data={"history": [{"time": datetime(2026, 7, 1, 12, 0, tzinfo=UTC)}]},
        timezone=zone,
        environment="example-prod",
        identity="reference",
        window=Window(NOW - timedelta(hours=1), NOW),
    )

    rendered = envelope.render()

    assert rendered["timezone"] == "Europe/Lisbon"
    assert rendered["data"]["history"][0]["time"] == "2026-07-01T13:00:00+01:00"
    assert rendered["window"] == {
        "start": "2026-11-06T11:00:00+00:00",
        "end": "2026-11-06T12:00:00+00:00",
    }
    assert rendered["identity"] == "reference identity"
    assert rendered["partial"] is False
    own = Envelope(data={}, timezone=zone, environment="example-prod", identity="own")
    assert own.render()["identity"] == "own identity, not verified"
    assert Envelope(data={}, timezone=zone).render()["identity"] is None


@spec("FR-004")
def test_every_error_reason_has_a_message_and_only_some_a_fix() -> None:
    for reason in ErrorReason:
        error = ToolError(reason, "detail")
        assert error.message.startswith(reason.describe())
        assert error.message.endswith("detail")
    assert ToolError(ErrorReason.INVALID_CONFIG, "x").fix == "opscout config validate"
    assert ToolError(ErrorReason.PROFILE_MISSING, "x").fix == "aws configure sso"
    assert ToolError(ErrorReason.THROTTLED, "x").fix is None
    login = ToolError(ErrorReason.LOGIN_EXPIRED, "x", fix="aws sso login --profile example-prod")
    assert login.render() == {
        "reason": "login-expired",
        "message": login.message,
        "fix": "aws sso login --profile example-prod",
    }
