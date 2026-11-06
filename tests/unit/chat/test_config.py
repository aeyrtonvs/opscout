# SPDX-License-Identifier: Apache-2.0
"""The chat setting and its keychain items (spec 008, FR-001 to FR-003)."""

from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest
import yaml

from opscout.core.config import (
    KEYCHAIN_ITEMS,
    ChatSetting,
    Configuration,
    Daemon,
    InvalidConfigError,
    schema_text,
)
from opscout.services.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "chat.yaml"

SECRETS = """\
  secrets:
    slack_bot_token:
      service: opscout-slack-bot
    slack_app_token:
      service: opscout-slack-app
"""
CHAT = "daemon:\n  chat:\n    service: slack\n    user: UEXAMPLE01\n" + SECRETS


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


@spec("FR-001")
def test_the_chat_setting_is_optional_and_additive() -> None:
    assert configuration("").daemon.chat is None
    assert configuration(CHAT).daemon.chat == ChatSetting(service="slack", user="UEXAMPLE01")
    compat = parse_config(COMPAT.read_bytes(), str(COMPAT)).daemon.chat
    assert compat is not None


@spec("FR-001")
@pytest.mark.parametrize(
    "chat",
    [
        "    service: teams\n    user: UEXAMPLE01\n",
        "    service: slack\n    user: uexample01\n",
        "    service: slack\n    user: CEXAMPLE01\n",
        "    service: slack\n    user: U1\n",
        f"    service: slack\n    user: U{'A' * 21}\n",
        "    service: slack\n",
        "    service: slack\n    user: UEXAMPLE01\n    token: x\n",
    ],
)
def test_bad_chat_settings_are_refused(chat: str) -> None:
    with pytest.raises(InvalidConfigError):
        configuration(f"daemon:\n  chat:\n{chat}{SECRETS}")


@spec("FR-002")
@pytest.mark.parametrize("missing", ["slack_bot_token", "slack_app_token"])
def test_chat_needs_both_tokens_by_reference(missing: str) -> None:
    other = {"slack_bot_token": "slack_app_token", "slack_app_token": "slack_bot_token"}[missing]
    text = (
        "daemon:\n  chat:\n    service: slack\n    user: UEXAMPLE01\n"
        f"  secrets:\n    {other}:\n      service: opscout-example\n"
    )
    with pytest.raises(InvalidConfigError) as error:
        configuration(text)
    assert missing in error.value.problems[0].message


@spec("FR-002")
def test_the_tokens_are_known_keychain_items() -> None:
    assert {"claude_token", "slack_bot_token", "slack_app_token"} <= set(KEYCHAIN_ITEMS)
    with pytest.raises(InvalidConfigError):
        configuration("daemon:\n  secrets:\n    slack_bot_token: xoxb-the-value\n")


@spec("FR-001")
def test_gateway_is_a_reserved_name() -> None:
    with pytest.raises(InvalidConfigError):
        configuration('daemon:\n  jobs:\n    gateway:\n      at: "09:30"\n')


@spec("FR-003")
def test_without_chat_the_daemon_section_is_as_in_spec_007() -> None:
    assert Daemon().chat is None
    assert configuration('daemon:\n  jobs:\n    check:\n      at: "09:30"\n').daemon.chat is None


@spec("FR-001")
def test_the_schema_refuses_what_the_loader_refuses() -> None:
    validator = jsonschema.Draft202012Validator(yaml.safe_load(schema_text()))
    good = yaml.safe_load(f"schema_version: 1\n{CHAT}")
    assert list(validator.iter_errors(good)) == []
    for bad in (
        {"chat": {"service": "teams", "user": "UEXAMPLE01"}},
        {"chat": {"service": "slack", "user": "lowercase"}},
        {"chat": {"service": "slack"}},
    ):
        assert list(validator.iter_errors({"schema_version": 1, "daemon": bad})) != [], bad
