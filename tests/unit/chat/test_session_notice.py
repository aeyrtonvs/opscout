# SPDX-License-Identifier: Apache-2.0
"""The SessionStart lines about the gateway (spec 008, FR-021)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from opscout.core.chat import GatewayStatus
from opscout.core.config import ChatSetting, Daemon, JobSettings, KeychainRef
from opscout.services.daemon import GatewayView, session_notices
from tests.unit.chat.fakes import ZONE

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=ZONE)
LOG = Path("/example/log/gateway.log")
REF = KeychainRef(service="opscout-example")
CHAT = Daemon(
    chat=ChatSetting(service="slack", user="UEXAMPLE01"),
    secrets={"slack_bot_token": REF, "slack_app_token": REF},
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


def view(status: GatewayStatus | None) -> GatewayView:
    return GatewayView(configured=True, status=status, log=LOG)


def seen(minutes: int, state: str = "connected", reason: str | None = None) -> GatewayStatus:
    at = NOW - timedelta(minutes=minutes)
    return GatewayStatus(state=state, since=at, last_seen=at, reason=reason)  # type: ignore[arg-type]


@spec("FR-021")
def test_a_gateway_not_installed_is_reported() -> None:
    assert session_notices(CHAT, {}, {}, NOW, view(None)) == (
        "opscout scheduled jobs:\n- gateway: not installed (run opscout daemon install)"
    )


@spec("FR-021")
@pytest.mark.parametrize(
    ("status", "line"),
    [
        (
            GatewayStatus(state="connecting", since=NOW - timedelta(hours=3), last_seen=NOW),
            "- gateway: not connected since 2026-11-05 07:00 (see /example/log/gateway.log)",
        ),
        (seen(20), "- gateway: not running since 2026-11-05 09:40 (see /example/log/gateway.log)"),
        (
            seen(1, "stopped", "token rejected (invalid_auth)"),
            "- gateway: stopped: token rejected (invalid_auth) "
            "(run opscout daemon install to start it again)",
        ),
    ],
)
def test_a_gateway_down_for_15_minutes_or_stopped_is_reported(
    status: GatewayStatus, line: str
) -> None:
    installed = {"gateway": NOW - timedelta(days=1)}
    assert session_notices(CHAT, {}, installed, NOW, view(status)) == (
        f"opscout scheduled jobs:\n{line}"
    )
    retrying = GatewayStatus(state="connecting", since=NOW - timedelta(minutes=5), last_seen=NOW)
    assert session_notices(CHAT, {}, installed, NOW, view(retrying)) is None


@spec("FR-021")
def test_a_gateway_that_never_wrote_is_reported_15_minutes_after_install() -> None:
    assert (
        session_notices(CHAT, {}, {"gateway": NOW - timedelta(minutes=5)}, NOW, view(None)) is None
    )
    assert session_notices(CHAT, {}, {"gateway": NOW - timedelta(minutes=20)}, NOW, view(None)) == (
        "opscout scheduled jobs:\n- gateway: never connected (see /example/log/gateway.log)"
    )


@spec("FR-021")
def test_nothing_when_connected_or_chat_is_off() -> None:
    installed = {"gateway": NOW - timedelta(days=1)}
    assert session_notices(CHAT, {}, installed, NOW, view(seen(1))) is None
    assert session_notices(Daemon(), {}, {}, NOW, None) is None
    jobs = Daemon(jobs={"check": JobSettings(at="09:30")})
    assert session_notices(jobs, {}, {"check": NOW - timedelta(days=1)}, NOW, None) is not None
    assert session_notices(CHAT, {}, None, NOW, view(seen(1))) is None  # no scheduler here
