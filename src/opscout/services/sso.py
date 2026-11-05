# SPDX-License-Identifier: Apache-2.0
"""The SSO check: find the logins, judge each cached token, say what to do (spec 005).

Everything here is pure: the entrypoints read the AWS config and the cache files and pass
their text in. A cache file holds tokens and a client secret; ``judge`` takes only the
expiry and whether a token is present, and nothing else leaves it (Principle III).
"""

import configparser
import hashlib
import json
import shlex
from datetime import UTC, datetime, tzinfo

from opscout.core.config import Sso
from opscout.core.sso import AwsConfigError, AwsSso, SessionCheck, SessionState, SsoSession


def cache_key(value: str) -> str:
    """Return the cache file's name for a session name or a start URL, as the AWS CLI does."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # noqa: S324  (a file name, not security)


def find_sessions(text: str) -> AwsSso:
    """Return the SSO sessions and older SSO profiles of an AWS config, in file order.

    Several profiles on one session, or older profiles on one start URL, share one token,
    so each is listed once. Raises ``AwsConfigError`` when the text cannot be parsed.
    """
    parser = configparser.RawConfigParser(
        strict=False, interpolation=None, default_section="\x00none"
    )
    try:
        parser.read_string(text)
    except configparser.Error as error:
        line = getattr(error, "lineno", None)
        where = f" at line {line}" if line else ""
        raise AwsConfigError(
            f"the AWS config cannot be parsed ({type(error).__name__}{where})"
        ) from None
    sessions: list[SsoSession] = []
    by_url: dict[str, SsoSession] = {}
    profiles: dict[str, str | SsoSession] = {}
    for section in parser.sections():
        kind, name = _section(section)
        if kind == "sso-session":
            if name not in {session.name for session in sessions if session.kind == kind}:
                sessions.append(SsoSession(name, "sso-session", cache_key(name)))
            continue
        if kind != "profile":
            continue
        options = parser[section]
        if session_name := options.get("sso_session", "").strip():
            profiles[name] = session_name
        elif url := options.get("sso_start_url", "").strip():
            if url not in by_url:
                by_url[url] = SsoSession(name, "profile", cache_key(url))
                sessions.append(by_url[url])
            profiles[name] = by_url[url]
    named = {session.name: session for session in sessions if session.kind == "sso-session"}
    resolved: dict[str, SsoSession] = {}
    for profile, target in profiles.items():
        session = named.get(target) if isinstance(target, str) else target
        if session is not None:
            resolved[profile] = session
    return AwsSso(sessions=tuple(sessions), profiles=resolved)


def _section(section: str) -> tuple[str, str]:
    """Return a section's kind and name, split the way the AWS CLI splits it, or two blanks.

    Like botocore, the header is split as shell words and must hold exactly two of them
    (``[default]`` stands for the profile ``default``); anything else is not a profile or a
    session.
    """
    try:
        words = shlex.split(section)
    except ValueError:
        return "", ""
    if words == ["default"]:
        return "profile", "default"
    if len(words) != 2:
        return "", ""
    return words[0], words[1]


def select(found: AwsSso, settings: Sso) -> list[SsoSession | str]:
    """Return the logins to check, in order; a listed name the config lacks stays a string.

    A listed name is an SSO session's name first, then a profile's: an older profile stands
    for itself, a profile on an SSO session for that session.
    """
    if not settings.enabled:
        return []
    if settings.sessions is None:
        return list(found.sessions)
    named = {session.name: session for session in found.sessions if session.kind == "sso-session"}
    chosen: list[SsoSession | str] = []
    for name in settings.sessions:
        pick: SsoSession | str = named.get(name) or found.profiles.get(name) or name
        if pick not in chosen:
            chosen.append(pick)
    return chosen


def judge(session: SsoSession, text: str | None, now: datetime) -> SessionCheck:
    """Return the state of one cached token; ``text`` is None when there is no cache file."""

    def check(state: SessionState, **found: datetime | str) -> SessionCheck:
        return SessionCheck(session.name, session.kind, state, **found)  # type: ignore[arg-type]

    if text is None:
        return check(SessionState.NOT_LOGGED_IN)
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return check(SessionState.UNREADABLE, reason="not valid JSON")
    if not isinstance(document, dict):
        return check(SessionState.UNREADABLE, reason="not a JSON object")
    has_token = "accessToken" in document
    expiry = document.get("expiresAt")
    del document
    if not has_token:
        # The AWS CLI refuses a cached token without one, so a new login is needed.
        return check(SessionState.NOT_LOGGED_IN)
    if not isinstance(expiry, str):
        return check(SessionState.UNREADABLE, reason="no expiry")
    expires_at = _expiry(expiry)
    if expires_at is None:
        return check(SessionState.UNREADABLE, reason="an expiry in an unknown format")
    state = SessionState.VALID if expires_at > now else SessionState.EXPIRED
    return check(state, expires_at=expires_at)


def _expiry(text: str) -> datetime | None:
    """Read an ISO 8601 time with a time zone, or the older ``…UTC`` form; otherwise None."""
    if text.endswith("UTC"):
        text = text.removesuffix("UTC") + "+00:00"
    if "T" not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def login_command(session: SsoSession | SessionCheck) -> str:
    """Return the command that logs in to one session."""
    flag = "--sso-session" if session.kind == "sso-session" else "--profile"
    return f"aws sso login {flag} {shlex.quote(session.name)}"


def render_warning(
    checks: list[SessionCheck], zone: tzinfo | None = None, note: str | None = None
) -> str | None:
    """Return the session-start warning, or None when every checked login is valid.

    Times are shown in ``zone``, or in the machine's local time for each instant.
    """
    attention = [check for check in checks if check.needs_login]
    if not attention:
        return None
    lines = [
        f"opscout SSO check: attention needed for {len(attention)} of {len(checks)} SSO "
        "sessions before AWS commands will work.",
        *(f"- {_line(check, zone)}" for check in attention),
    ]
    return "\n".join([*lines, *_note(note)]) + "\n"


def render_status(
    checks: list[SessionCheck], zone: tzinfo | None = None, note: str | None = None
) -> str:
    """Return one line per checked login, for ``opscout sso check``."""
    if not checks:
        lines = ["No SSO session or SSO profile in the AWS config."]
    else:
        lines = [_line(check, zone) for check in checks]
    return "\n".join([*lines, *_note(note)]) + "\n"


def _note(note: str | None) -> list[str]:
    if note is None:
        return []
    return [
        f"The opscout configuration could not be used ({note}), so every SSO session was checked."
    ]


def _line(check: SessionCheck, zone: tzinfo | None) -> str:
    when = (
        check.expires_at.astimezone(zone).strftime("%Y-%m-%d %H:%M") + " (local time)"
        if check.expires_at is not None
        else ""
    )
    match check.state:
        case SessionState.VALID:
            return f"{check.name}: valid until {when}"
        case SessionState.EXPIRED:
            return f"{check.name}: expired at {when}; run: {login_command(check)}"
        case SessionState.NOT_LOGGED_IN:
            return f"{check.name}: not logged in; run: {login_command(check)}"
        case SessionState.UNREADABLE:
            return (
                f"{check.name}: could not be checked ({check.reason}); run: {login_command(check)}"
            )
    return f"{check.name}: unknown: no SSO session or SSO profile of that name in the AWS config"
