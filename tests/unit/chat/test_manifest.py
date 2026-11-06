# SPDX-License-Identifier: Apache-2.0
"""The Slack app's manifest asks for the least access (spec 008, FR-004; research R2)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

MANIFEST = Path(__file__).resolve().parents[3] / "deploy" / "slack" / "opscout-app-manifest.yaml"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


def manifest() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return data


@spec("FR-004")
def test_the_app_writes_dms_and_reads_nothing() -> None:
    scopes = manifest()["oauth_config"]["scopes"]
    assert sorted(scopes["bot"]) == ["chat:write", "im:write"]
    assert scopes.get("user", []) == []


@spec("FR-004")
def test_it_receives_no_events_and_has_no_public_address() -> None:
    data = manifest()
    settings = data["settings"]
    assert "event_subscriptions" not in settings
    assert settings["socket_mode_enabled"] is True
    assert settings["interactivity"] == {"is_enabled": True}
    text = MANIFEST.read_text(encoding="utf-8")
    assert "request_url" not in text
    assert "http" not in text.lower().replace("https://api.slack.com", "")


@spec("FR-004")
def test_the_user_cannot_write_to_the_app() -> None:
    home = manifest()["features"]["app_home"]
    assert home["messages_tab_read_only_enabled"] is True
    assert home["home_tab_enabled"] is False


@spec("FR-005")
def test_the_reference_gives_the_setup() -> None:
    reference = (MANIFEST.parents[2] / "docs" / "reference" / "daemon.md").read_text(
        encoding="utf-8"
    )
    for step in (
        "deploy/slack/opscout-app-manifest.yaml",
        "connections:write",
        "Copy member ID",
        "opscout secret set slack_bot_token",
        "opscout secret set slack_app_token",
        "opscout daemon install",
    ):
        assert step in reference, step
