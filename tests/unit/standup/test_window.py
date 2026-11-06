# SPDX-License-Identifier: Apache-2.0
"""The covered days (spec 009, FR-003; research R4)."""

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from opscout.services.standup import describe_days, window_for
from tests.unit.standup.fakes import ZONE, at

WEEK = ["mon", "tue", "wed", "thu", "fri"]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@spec("FR-003")
def test_a_weekday_covers_the_day_before() -> None:
    window = window_for(at(5, 9, 45), WEEK)  # Thursday
    assert (window.start, window.end) == (at(4, 0), at(5, 0))
    assert window.days == (date(2026, 11, 4),)
    assert window.now == at(5, 9, 45)
    assert describe_days(window) == "Wednesday 4"


@spec("FR-003")
def test_a_monday_covers_friday_to_sunday() -> None:
    window = window_for(at(9, 9, 45), WEEK)
    assert (window.start, window.end) == (at(6, 0), at(9, 0))
    assert window.days == (date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8))
    assert describe_days(window) == "Friday 6 to Sunday 8"


@spec("FR-003")
def test_a_custom_week() -> None:
    window = window_for(at(10, 9), ["tue", "thu"])  # a Tuesday: back to last Thursday
    assert window.start == at(5, 0)
    assert len(window.days) == 5


@spec("FR-003")
def test_a_daylight_saving_week_keeps_local_midnights() -> None:
    zone = ZoneInfo("America/New_York")  # clocks go back on Sunday 1 November 2026
    now = datetime(2026, 11, 2, 9, 45, tzinfo=zone)
    window = window_for(now, WEEK)
    assert window.start.replace(tzinfo=None) == datetime(2026, 10, 30, 0, 0)
    assert window.end.replace(tzinfo=None) == datetime(2026, 11, 2, 0, 0)
    assert (
        window.end.timestamp() - window.start.timestamp()
        == timedelta(days=3, hours=1).total_seconds()
    )
    assert window.start.utcoffset() != window.end.utcoffset()
    assert ZONE != UTC


@spec("FR-003")
def test_a_fixed_offset_other_than_the_machine_s_is_kept() -> None:
    far = timezone(timedelta(hours=13))
    window = window_for(datetime(2026, 11, 5, 9, 45, tzinfo=far), WEEK)
    assert window.start == datetime(2026, 11, 4, 0, 0, tzinfo=far)
