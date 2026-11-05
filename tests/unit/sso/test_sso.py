# SPDX-License-Identifier: Apache-2.0
"""The SSO check hook: the `sso` section, the check, the commands, the hook (spec 005).

Every test is tied to its requirements with ``@pytest.mark.spec("005", ...)``. AWS configs
and token caches are built in a temporary home with reserved values only; the planted
token values below must never appear in any output.
"""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from opscout.core.config import Configuration, InvalidConfigError, Sso
from opscout.core.sso import (
    MAX_CACHE_BYTES,
    AwsConfigError,
    AwsSso,
    SessionCheck,
    SessionState,
    SsoSession,
)
from opscout.entrypoints.cli import main
from opscout.entrypoints.sso import check_sessions
from opscout.services.config import parse_config
from opscout.services.sso import (
    cache_key,
    find_sessions,
    judge,
    login_command,
    render_status,
    render_warning,
    select,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = REPO_ROOT / "specs" / "005-sso-check-hook" / "spec.md"
PLUGIN = REPO_ROOT / "plugins" / "opscout"
COMPAT = REPO_ROOT / "tests" / "unit" / "config_contract" / "compat" / "v1" / "sso.yaml"

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LOCAL = timezone(timedelta(hours=-6))
START_URL = "https://example.com/start"
PLANTED = (
    "plantedaccesstokenvalue",
    "plantedrefreshtokenvalue",
    "plantedclientsecretvalue",
    "plantedclientidvalue",
)

SESSION = SsoSession("example-session", "sso-session", cache_key("example-session"))
PROFILE = SsoSession("example-prod", "profile", cache_key(START_URL))


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 005."""
    return pytest.mark.spec("005", requirement)


def configuration(text: str) -> Configuration:
    return parse_config(f"schema_version: 1\n{text}".encode(), "config.yaml")


def token(expires: str | None = "2026-11-04T18:00:00Z", **extra: Any) -> str:
    """Return a cache file's text, as the AWS CLI writes it, with planted secret values."""
    body: dict[str, Any] = {
        "startUrl": START_URL,
        "region": "us-east-1",
        "accessToken": PLANTED[0],
        "refreshToken": PLANTED[1],
        "clientId": PLANTED[3],
        "clientSecret": PLANTED[2],
        "registrationExpiresAt": "2027-01-01T00:00:00Z",
    }
    if expires is not None:
        body["expiresAt"] = expires
    body.update(extra)
    return json.dumps(body)


AWS_CONFIG = f"""\
[default]
region = us-east-1

[sso-session example-session]
sso_start_url = {START_URL}/other
sso_region = us-east-1
sso_registration_scopes = sso:account:access

[profile example-dev]
sso_session = example-session
sso_account_id = 123456789012
sso_role_name = ReadOnly

[profile example-test]
sso_session = example-session
sso_account_id = 123456789012
sso_role_name = ReadOnly
s3 =
  max_concurrent_requests = 10

[profile example-prod]
sso_start_url = {START_URL}
sso_region = us-east-1
sso_account_id = 123456789012
sso_role_name = ReadOnly

[profile example-prod-admin]
sso_start_url = {START_URL}
sso_account_id = 123456789012
sso_role_name = Admin

[profile example-keys]
region = us-east-1
"""


def make_home(
    tmp_path: Path, config: str | None = AWS_CONFIG, tokens: dict[str, str] | None = None
) -> Path:
    """Build a home with an AWS config and cache files, keyed by session name or start URL."""
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    if config is not None:
        (home / ".aws" / "config").write_text(config, encoding="utf-8")
    if tokens is not None:
        cache = home / ".aws" / "sso" / "cache"
        cache.mkdir(parents=True)
        for key, text in tokens.items():
            (cache / f"{cache_key(key)}.json").write_text(text, encoding="utf-8")
    return home


def assert_no_planted_value(text: str) -> None:
    for value in (*PLANTED, START_URL):
        assert value not in text


# The sso section (User Story 3)


@spec("FR-009")
def test_the_sso_section_is_optional_and_additive() -> None:
    assert configuration("").sso == Sso()
    assert Sso().enabled is True
    assert Sso().sessions is None
    compat = parse_config(COMPAT.read_bytes(), str(COMPAT)).sso
    assert compat.enabled is True
    assert compat.sessions == ["example-session", "example-prod"]


@spec("FR-009")
@pytest.mark.parametrize(
    "text",
    [
        "sso:\n  enabled: 1\n",
        "sso:\n  enabled: 'yes'\n",
        "sso:\n  sessions: []\n",
        "sso:\n  sessions: [a, a]\n",
        "sso:\n  sessions: ['has space']\n",
        "sso:\n  sessions: ['']\n",
        f"sso:\n  sessions: [{'x' * 101}]\n",
        "sso:\n  sessions: [" + ", ".join(f"s{n}" for n in range(51)) + "]\n",
        "sso:\n  other: true\n",
    ],
)
def test_the_sso_section_refuses_bad_values(text: str) -> None:
    with pytest.raises(InvalidConfigError):
        configuration(text)


# Finding the sessions (User Story 1)


@spec("FR-004")
def test_sso_sessions_and_older_profiles_are_found_once_each() -> None:
    found = find_sessions(AWS_CONFIG)

    assert found.sessions == (SESSION, PROFILE)
    assert found.profiles == {
        "example-dev": SESSION,
        "example-test": SESSION,
        "example-prod": PROFILE,
        "example-prod-admin": PROFILE,
    }


@spec("FR-005")
def test_the_cache_key_is_the_sha1_of_the_session_name_or_start_url() -> None:
    assert cache_key("example-session") == hashlib.sha1(b"example-session").hexdigest()  # noqa: S324
    assert PROFILE.cache_key == hashlib.sha1(START_URL.encode()).hexdigest()  # noqa: S324


@spec("FR-004")
@pytest.mark.parametrize(
    "text",
    [
        "",
        "[default]\nregion = us-east-1\n",
        "[profile example-keys]\nregion = us-east-1\n",
        f"[services example]\nsso_start_url = {START_URL}\n",
        f"[profile]\nsso_start_url = {START_URL}\n",
    ],
)
def test_a_config_without_sso_has_no_sessions(text: str) -> None:
    assert find_sessions(text) == AwsSso(sessions=(), profiles={})


@spec("FR-004")
def test_section_names_are_split_as_the_aws_cli_splits_them() -> None:
    text = (
        '[sso-session "quoted"]\n'
        "[sso-session  spaced]\n"
        "[sso-session spaced]\n"
        "[profile two words]\nsso_start_url = https://example.com/two\n"
        "[profile\ttabbed]\nsso_start_url = https://example.com/tab\n"
        "[sso-session 'unclosed]\n"
    )

    assert find_sessions(text).sessions == (
        SsoSession("quoted", "sso-session", cache_key("quoted")),
        SsoSession("spaced", "sso-session", cache_key("spaced")),
        SsoSession("tabbed", "profile", cache_key("https://example.com/tab")),
    )


@spec("FR-004")
def test_a_profile_on_a_session_does_not_add_its_start_url() -> None:
    text = f"[profile both]\nsso_session = s\nsso_start_url = {START_URL}\n[sso-session s]\n"
    assert find_sessions(text).sessions == (SsoSession("s", "sso-session", cache_key("s")),)


@spec("FR-004")
def test_the_default_profile_can_hold_its_own_start_url() -> None:
    found = find_sessions(f"[default]\nsso_start_url = {START_URL}\n")
    assert found.sessions == (SsoSession("default", "profile", cache_key(START_URL)),)


@spec("FR-009")
def test_a_profile_on_an_undefined_session_is_unknown() -> None:
    found = find_sessions("[profile lost]\nsso_session = nowhere\n")

    assert found == AwsSso(sessions=(), profiles={})
    assert select(found, Sso(sessions=["lost"])) == ["lost"]


@spec("FR-003")
@pytest.mark.parametrize("text", ["region = us-east-1\n", "[profile a\n", "[profile a]\nnovalue\n"])
def test_an_unparsable_config_cannot_be_checked(text: str) -> None:
    with pytest.raises(AwsConfigError, match="AWS config"):
        find_sessions(text)


# Judging a cached token (User Stories 1 and 2)


@spec("FR-006")
@pytest.mark.parametrize(
    ("text", "state", "expires"),
    [
        (token("2026-11-04T18:00:00Z"), SessionState.VALID, datetime(2026, 11, 4, 18, tzinfo=UTC)),
        (
            token("2026-11-04T18:00:00UTC"),
            SessionState.VALID,
            datetime(2026, 11, 4, 18, tzinfo=UTC),
        ),
        (
            token("2026-11-04T09:12:00Z"),
            SessionState.EXPIRED,
            datetime(2026, 11, 4, 9, 12, tzinfo=UTC),
        ),
        (
            token("2026-11-04T09:12:00UTC"),
            SessionState.EXPIRED,
            datetime(2026, 11, 4, 9, 12, tzinfo=UTC),
        ),
        (token("2026-11-04T12:00:00Z"), SessionState.EXPIRED, NOW),
        (
            token("2026-11-04T18:00:00.000Z"),
            SessionState.VALID,
            datetime(2026, 11, 4, 18, tzinfo=UTC),
        ),
        (
            token("2026-11-04T18:00:00+01:00"),
            SessionState.VALID,
            datetime(2026, 11, 4, 17, tzinfo=UTC),
        ),
        (None, SessionState.NOT_LOGGED_IN, None),
        (json.dumps({"expiresAt": "2026-11-04T18:00:00Z"}), SessionState.NOT_LOGGED_IN, None),
    ],
)
def test_a_cached_token_is_judged_by_its_expiry(
    text: str | None, state: SessionState, expires: datetime | None
) -> None:
    assert judge(SESSION, text, NOW) == SessionCheck(
        "example-session", "sso-session", state, expires_at=expires
    )


@spec("FR-006")
def test_an_expired_token_that_could_be_renewed_is_still_expired() -> None:
    renewable = token("2026-11-04T11:59:00Z", registrationExpiresAt="2027-06-01T00:00:00Z")
    assert judge(SESSION, renewable, NOW).state is SessionState.EXPIRED


@spec("FR-006")
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ('"text"', "not a JSON object"),
        (token(None), "no expiry"),
        (token(None, expiresAt=1762300800), "no expiry"),
        (token("tomorrow"), "an expiry in an unknown format"),
        (token("2026-11-04T18:00:00"), "an expiry in an unknown format"),
        (token("2026-11-04"), "an expiry in an unknown format"),
        (token("2026-13-04T18:00:00Z"), "an expiry in an unknown format"),
    ],
)
def test_a_damaged_cache_file_could_not_be_checked(text: str, reason: str) -> None:
    check = judge(SESSION, text, NOW)

    assert check.state is SessionState.UNREADABLE
    assert check.reason == reason


@spec("FR-007")
@pytest.mark.parametrize(
    "text",
    [token(), token("2026-11-04T09:12:00Z"), token(None), token("not-a-date"), "{" + PLANTED[0]],
)
def test_no_cache_value_but_the_expiry_leaves_the_check(text: str) -> None:
    check = judge(SESSION, text, NOW)
    rendered = repr(check) + render_status([check], LOCAL) + (render_warning([check], LOCAL) or "")

    assert_no_planted_value(rendered)


# Rendering (User Story 1)


@spec("FR-002")
def test_nothing_is_said_when_every_login_is_valid() -> None:
    valid = SessionCheck("example-session", "sso-session", SessionState.VALID, NOW)
    assert render_warning([valid], LOCAL) is None
    assert render_warning([], LOCAL) is None


@spec("FR-002")
def test_the_warning_lists_each_session_that_needs_a_login() -> None:
    checks = [
        SessionCheck(
            "example-session",
            "sso-session",
            SessionState.EXPIRED,
            datetime(2026, 11, 4, 15, 12, tzinfo=UTC),
        ),
        SessionCheck("ok", "sso-session", SessionState.VALID, NOW),
        SessionCheck("example-prod", "profile", SessionState.NOT_LOGGED_IN),
        SessionCheck("odd name", "sso-session", SessionState.UNREADABLE, reason="not valid JSON"),
        SessionCheck("example-missing", None, SessionState.UNKNOWN),
    ]

    assert render_warning(checks, LOCAL) == (
        "opscout SSO check: attention needed for 4 of 5 SSO sessions before AWS commands will "
        "work.\n"
        "- example-session: expired at 2026-11-04 09:12 (local time); "
        "run: aws sso login --sso-session example-session\n"
        "- example-prod: not logged in; run: aws sso login --profile example-prod\n"
        "- odd name: could not be checked (not valid JSON); "
        "run: aws sso login --sso-session 'odd name'\n"
        "- example-missing: unknown: no SSO session or SSO profile of that name "
        "in the AWS config\n"
    )


@spec("FR-002")
def test_the_warning_says_when_the_configuration_was_not_used() -> None:
    expired = SessionCheck("example-session", "sso-session", SessionState.EXPIRED, NOW)
    warning = render_warning([expired], LOCAL, note="it has 2 problems")

    assert warning is not None
    assert warning.endswith(
        "The opscout configuration could not be used (it has 2 problems), so every SSO "
        "session was checked.\n"
    )


@spec("FR-008")
def test_the_status_lists_every_session() -> None:
    checks = [
        SessionCheck(
            "ok", "sso-session", SessionState.VALID, datetime(2026, 11, 4, 18, tzinfo=UTC)
        ),
        SessionCheck(
            "example-prod", "profile", SessionState.EXPIRED, datetime(2026, 11, 4, 9, tzinfo=UTC)
        ),
    ]

    assert render_status(checks, LOCAL) == (
        "ok: valid until 2026-11-04 12:00 (local time)\n"
        "example-prod: expired at 2026-11-04 03:00 (local time); "
        "run: aws sso login --profile example-prod\n"
    )
    assert render_status([], LOCAL) == "No SSO session or SSO profile in the AWS config.\n"


@spec("FR-002")
def test_the_login_command_names_the_session_or_the_profile() -> None:
    assert login_command(SESSION) == "aws sso login --sso-session example-session"
    assert login_command(PROFILE) == "aws sso login --profile example-prod"
    odd = SsoSession("it's", "profile", "x")
    assert login_command(odd) == "aws sso login --profile 'it'\"'\"'s'"


# Selecting (User Story 3)


@spec("FR-009")
def test_by_default_every_session_is_checked() -> None:
    assert select(find_sessions(AWS_CONFIG), Sso()) == [SESSION, PROFILE]


@spec("FR-009")
def test_a_list_checks_only_those_sessions_in_its_order() -> None:
    found = find_sessions(AWS_CONFIG)
    settings = Sso(sessions=["example-prod-admin", "example-dev", "example-session", "nope"])

    assert select(found, settings) == [PROFILE, SESSION, "nope"]


@spec("FR-009")
def test_a_session_name_wins_over_a_profile_name() -> None:
    text = "[sso-session same]\n[profile same]\nsso_session = other\n[sso-session other]\n"
    found = find_sessions(text)
    assert select(found, Sso(sessions=["same"])) == [found.sessions[0]]


@spec("FR-009")
def test_the_check_can_be_turned_off() -> None:
    assert select(find_sessions(AWS_CONFIG), Sso(enabled=False)) == []


# Reading the files (User Story 2)


@spec("FR-005")
def test_the_sessions_are_checked_from_the_files(tmp_path: Path) -> None:
    home = make_home(
        tmp_path, tokens={"example-session": token(), START_URL: token("2026-11-01T00:00:00Z")}
    )

    checks = check_sessions(Sso(), {}, home, NOW)

    assert [(check.name, check.state) for check in checks] == [
        ("example-session", SessionState.VALID),
        ("example-prod", SessionState.EXPIRED),
    ]


@spec("FR-004")
def test_aws_config_file_names_another_config(tmp_path: Path) -> None:
    home = make_home(tmp_path, tokens={})
    other = tmp_path / "other-config"
    other.write_text("[sso-session elsewhere]\n", encoding="utf-8")

    checks = check_sessions(Sso(), {"AWS_CONFIG_FILE": str(other)}, home, NOW)

    assert checks == [SessionCheck("elsewhere", "sso-session", SessionState.NOT_LOGGED_IN)]


@spec("FR-004")
def test_without_an_aws_config_there_is_nothing_to_check(tmp_path: Path) -> None:
    assert check_sessions(Sso(), {}, make_home(tmp_path, config=None), NOW) == []


@spec("FR-005")
def test_a_missing_cache_directory_means_not_logged_in(tmp_path: Path) -> None:
    checks = check_sessions(Sso(), {}, make_home(tmp_path), NOW)
    assert {check.state for check in checks} == {SessionState.NOT_LOGGED_IN}


@spec("FR-007")
def test_a_large_cache_file_is_not_read(tmp_path: Path) -> None:
    big = token() + " " * MAX_CACHE_BYTES
    home = make_home(tmp_path, tokens={"example-session": big})

    check = check_sessions(Sso(sessions=["example-session"]), {}, home, NOW)[0]

    assert check.state is SessionState.UNREADABLE
    assert check.reason == "larger than 64 KiB"


@spec("FR-007")
@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX modes")
def test_an_unreadable_cache_file_could_not_be_checked(tmp_path: Path) -> None:
    home = make_home(tmp_path, tokens={"example-session": token()})
    cache_file = home / ".aws" / "sso" / "cache" / f"{cache_key('example-session')}.json"
    cache_file.chmod(0)
    try:
        check = check_sessions(Sso(sessions=["example-session"]), {}, home, NOW)[0]
    finally:
        cache_file.chmod(0o600)

    assert check.state is SessionState.UNREADABLE
    assert check.reason == "it cannot be read (PermissionError)"


@spec("FR-007")
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_a_cache_path_that_is_not_a_regular_file_is_not_read(tmp_path: Path) -> None:
    home = make_home(tmp_path, tokens={})
    os.mkfifo(home / ".aws" / "sso" / "cache" / f"{cache_key('example-session')}.json")

    check = check_sessions(Sso(sessions=["example-session"]), {}, home, NOW)[0]

    assert check.state is SessionState.UNREADABLE
    assert check.reason == "not a regular file"


@spec("FR-004")
def test_aws_config_file_may_hold_variables(tmp_path: Path) -> None:
    home = make_home(tmp_path, config=None)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "aws").write_text("[sso-session elsewhere]\n", encoding="utf-8")
    environ = {"AWS_CONFIG_FILE": "$EXAMPLE_ROOT/configs/aws", "EXAMPLE_ROOT": str(tmp_path)}

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("EXAMPLE_ROOT", str(tmp_path))
        checks = check_sessions(Sso(), environ, home, NOW)

    assert [check.name for check in checks] == ["elsewhere"]


@spec("FR-007")
def test_an_aws_config_that_cannot_be_decoded_cannot_be_checked(tmp_path: Path) -> None:
    home = make_home(tmp_path, config=None)
    (home / ".aws" / "config").write_bytes(b"[sso-session \xff]\n")

    with pytest.raises(AwsConfigError, match="AWS config"):
        check_sessions(Sso(), {}, home, NOW)


@spec("FR-007")
def test_the_check_uses_no_network_no_program_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = make_home(tmp_path, tokens={"example-session": token()})
    before = sorted((path, path.stat().st_mtime_ns) for path in home.rglob("*"))

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the check must not reach out")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    checks = check_sessions(Sso(), {}, home, NOW)

    assert len(checks) == 2
    assert sorted((path, path.stat().st_mtime_ns) for path in home.rglob("*")) == before


@spec("FR-011")
def test_the_check_takes_under_100_ms_at_the_95th_percentile(tmp_path: Path) -> None:
    config = "".join(f"[sso-session example-{n}]\nsso_region = us-east-1\n" for n in range(20))
    home = make_home(tmp_path, config, {f"example-{n}": token() for n in range(20)})
    durations = []
    for _ in range(100):
        started = time.perf_counter()
        checks = check_sessions(Sso(), {}, home, NOW)
        durations.append(time.perf_counter() - started)

    assert len(checks) == 20
    assert sorted(durations)[94] < 0.1  # SC-003


# The commands and the hook (FR-001 to FR-003, FR-008)


@pytest.fixture
def utc() -> Iterator[None]:
    """Run in UTC, so local times in the output do not depend on the machine."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if saved is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = saved
    time.tzset()


@pytest.fixture
def aws_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, utc: None) -> Path:
    """A home whose example-session expired and whose example-prod is valid."""
    home = make_home(
        tmp_path,
        tokens={
            "example-session": token("2020-06-15T12:00:00Z"),
            START_URL: token("2099-06-15T12:00:00Z"),
        },
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AWS_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_config_dir", raising=False)
    monkeypatch.delenv("OPSCOUT_CONFIG", raising=False)
    return home


def config_dir(tmp_path: Path, text: str) -> Path:
    directory = tmp_path / "configuration"
    directory.mkdir()
    (directory / "config.yaml").write_text(f"schema_version: 1\n{text}", encoding="utf-8")
    return directory


def run_hook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", _Stdin('{"hook_event_name": "SessionStart"}'))
    code = main(["hook", "session-start", *args])
    out, err = capsys.readouterr()
    return code, out, err


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


@spec("FR-008")
def test_sso_check_lists_the_sessions_and_exits_1_when_a_login_is_needed(
    aws_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["sso", "check"])
    out = capsys.readouterr().out

    assert code == 1
    assert out.startswith("example-session: expired at 2020-06-15 ")
    assert "run: aws sso login --sso-session example-session" in out
    assert "example-prod: valid until 2099-06-15 " in out
    assert_no_planted_value(out)


@spec("FR-008")
def test_sso_check_exits_0_when_every_login_is_valid(
    aws_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = config_dir(tmp_path, "sso:\n  sessions: [example-prod]\n")

    assert main(["sso", "check", "--config", str(directory)]) == 0
    assert capsys.readouterr().out.startswith("example-prod: valid until 2099-06-15 ")


@spec("FR-008")
def test_sso_check_says_when_it_is_turned_off(
    aws_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = config_dir(tmp_path, "sso:\n  enabled: false\n")

    assert main(["sso", "check", "--config", str(directory)]) == 0
    assert capsys.readouterr().out == "The SSO check is turned off in the configuration.\n"


@spec("FR-008")
def test_sso_check_reports_an_unreadable_aws_config(
    aws_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (aws_home / ".aws" / "config").write_text("region = x\n", encoding="utf-8")

    assert main(["sso", "check"]) == 1
    assert capsys.readouterr().out.startswith(
        "opscout: the SSO check could not run: the AWS config"
    )


@spec("FR-002")
def test_the_hook_warns_the_user_and_tells_claude(
    aws_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_hook(monkeypatch, capsys)
    output = json.loads(out)

    assert (code, err) == (0, "")
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert output["hookSpecificOutput"]["additionalContext"] == output["systemMessage"]
    assert output["systemMessage"].startswith(
        "opscout SSO check: attention needed for 1 of 2 SSO sessions"
    )
    assert "aws sso login --sso-session example-session" in output["systemMessage"]
    assert "example-prod" not in output["systemMessage"]
    assert_no_planted_value(out)


@spec("FR-002")
@pytest.mark.parametrize("text", ["sso:\n  enabled: false\n", "sso:\n  sessions: [example-prod]\n"])
def test_the_hook_says_nothing_when_off_or_valid(
    aws_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_CONFIG_DIR", str(config_dir(tmp_path, text)))
    assert run_hook(monkeypatch, capsys) == (0, "", "")


@spec("FR-002")
def test_the_hook_says_nothing_without_sso(
    aws_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (aws_home / ".aws" / "config").unlink()
    assert run_hook(monkeypatch, capsys) == (0, "", "")


@spec("FR-002")
def test_the_hook_notes_an_invalid_configuration_and_checks_every_session(
    aws_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = config_dir(tmp_path, "sso:\n  enabled: maybe\n  sessions: [example-prod]\n")
    code, out, _ = run_hook(monkeypatch, capsys, "--config", str(directory))
    message = json.loads(out)["systemMessage"]

    assert code == 0
    assert "example-session" in message
    assert message.endswith(
        "The opscout configuration could not be used (it has 1 problem; run opscout config "
        "validate), so every SSO session was checked.\n"
    )


@spec("FR-002")
def test_a_missing_configuration_that_was_named_is_noted(
    aws_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "not-there"
    _, out, _ = run_hook(monkeypatch, capsys, "--config", str(missing))

    assert json.loads(out)["systemMessage"].endswith(
        f"could not be used ({missing}: no such directory), so every SSO session was checked.\n"
    )


@spec("FR-002")
def test_no_configuration_at_the_default_place_is_not_noted(
    aws_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = run_hook(monkeypatch, capsys)
    assert "configuration" not in json.loads(out)["systemMessage"]


@spec("FR-003")
def test_any_error_becomes_one_message_and_the_session_starts(
    aws_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("opscout.entrypoints.hook.check_sessions", broken)
    code, out, err = run_hook(monkeypatch, capsys)

    assert (code, err) == (0, "")
    assert json.loads(out) == {
        "systemMessage": "opscout: the SSO check could not run (RuntimeError)"
    }


@spec("FR-003")
def test_an_unreadable_aws_config_becomes_one_message(
    aws_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (aws_home / ".aws" / "config").write_text("[profile a\n", encoding="utf-8")
    code, out, _ = run_hook(monkeypatch, capsys)

    assert code == 0
    assert json.loads(out)["systemMessage"].startswith(
        "opscout: the SSO check could not run: the AWS config"
    )


@spec("FR-001")
def test_the_plugin_declares_the_session_start_hook() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = hooks["SessionStart"]
    (command,) = entry["hooks"]

    assert entry["matcher"] == "startup|resume|clear|fork"
    assert command["type"] == "command"
    assert command["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/opscout"
    assert command["args"] == ["hook", "session-start"]
    assert command["timeout"] == 10
    assert "onFailure" not in command
    assert "PreToolUse" in hooks


@spec("FR-011")
def test_the_hook_through_the_launcher_takes_under_a_second(tmp_path: Path) -> None:
    home = make_home(tmp_path, tokens={"example-session": token("2020-06-15T12:00:00Z")})
    uv = shutil.which("uv")
    assert uv is not None
    cache = subprocess.run(  # noqa: S603  (a fixed uv command)
        [uv, "cache", "dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "CLAUDE_PLUGIN_OPTION_", "OPSCOUT_"))
    }
    environment.update(HOME=str(home), UV_CACHE_DIR=cache)
    started = time.perf_counter()
    result = subprocess.run(  # noqa: S603  (the launcher under test)
        [str(PLUGIN / "bin" / "opscout"), "hook", "session-start"],
        input='{"hook_event_name": "SessionStart", "source": "startup"}',
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    elapsed = time.perf_counter() - started

    assert result.returncode == 0, result.stderr
    assert (
        "aws sso login --sso-session example-session" in json.loads(result.stdout)["systemMessage"]
    )
    assert elapsed < 1.0  # SC-003


def copy_plugin(tmp_path: Path, version: str) -> Path:
    """Copy the plugin outside any clone, as an install does, at a given version."""
    copy = tmp_path / "cache" / "opscout" / version
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("evals"))
    manifest = copy / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**data, "version": version}), encoding="utf-8")
    return copy / "bin" / "opscout"


def run_session_start(launcher: Path, path: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ}
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(  # noqa: S603  (the launcher under test)
        [str(launcher), "hook", "session-start"],
        input='{"hook_event_name": "SessionStart"}',
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def fake_uvx(tmp_path: Path, body: str) -> str:
    """Return a PATH whose uvx runs ``body``, ahead of the real PATH."""
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "uvx").write_text(f"#!{sys.executable}\nimport sys\n{body}\n", encoding="utf-8")
    (fake / "uvx").chmod(0o755)
    return f"{fake}{os.pathsep}{os.environ['PATH']}"


@spec("FR-003")
def test_without_a_release_the_hook_says_so_in_one_message(tmp_path: Path) -> None:
    result = run_session_start(copy_plugin(tmp_path, "0.0.0"))

    assert (result.returncode, result.stderr) == (0, "")
    message = json.loads(result.stdout)["systemMessage"]
    assert message.startswith("opscout: the SSO check could not run: there is no release")
    assert "\n" not in message


@spec("FR-003")
def test_an_engine_that_fails_to_start_becomes_one_message(tmp_path: Path) -> None:
    path = fake_uvx(tmp_path, "sys.stderr.write('offline\\n')\nsys.exit(1)")
    result = run_session_start(copy_plugin(tmp_path, "1.2.3"), path=path)

    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(result.stdout) == {
        "systemMessage": "opscout: the SSO check could not run: the engine exited with status 1"
    }


@spec("FR-001")
def test_the_engine_output_passes_through_the_launcher(tmp_path: Path) -> None:
    path = fake_uvx(tmp_path, 'print(\'{"systemMessage": "from the engine"}\')')
    result = run_session_start(copy_plugin(tmp_path, "1.2.3"), path=path)

    assert (result.returncode, result.stdout) == (0, '{"systemMessage": "from the engine"}\n')


# Traceability


@spec("FR-010")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for name, test in globals().items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "spec" and mark.args[0] == "005":
                proven.add(mark.args[1])

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []
