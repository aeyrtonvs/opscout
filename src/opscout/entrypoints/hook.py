# SPDX-License-Identifier: Apache-2.0
"""The plugin's hooks: the push guard (spec 004) and the session checks (specs 005, 007).

PreToolUse: Claude Code sends each Bash command here before it runs (``hooks/hooks.json``,
with ``onFailure: block``). The decision itself is pure (``opscout.services.ship``); this
module reads the event, asks git for the current branch and the remote's default branch, and
reads the protected patterns through the configuration's loader. When the configuration
cannot be read, main, master and the remote's default branch stay protected. An event the
hook cannot read exits 2, which blocks the command: the guard never fails open.

SessionStart: the SSO check warns the user and tells Claude which SSO logins are needed, and
the scheduled jobs that failed or did not run are named after it (spec 007, FR-028). It
cannot block a session, and any error becomes one message saying the checks could not run.
"""

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

from opscout.core.config import ConfigError, ConfigLocationError, Ship
from opscout.core.ship import DEFAULT_REMOTE, PushCommand, PushConfig, PushDecision
from opscout.core.sso import AwsConfigError
from opscout.entrypoints.config import load_config
from opscout.entrypoints.daemon import job_notices
from opscout.entrypoints.sso import check_sessions, sso_settings
from opscout.services.config import ConfigLocation
from opscout.services.ship import decide_push, read_command
from opscout.services.sso import render_warning

BLOCKED = 2


class HookError(Exception):
    """The event cannot be read; the command is blocked."""


def pre_tool_use(event_text: str, location: ConfigLocation) -> str:
    """Return the hook's output for one event: JSON with a decision, or nothing."""
    try:
        event: dict[str, Any] = json.loads(event_text)
        tool = event["tool_name"]
        command = event["tool_input"]["command"] if tool == "Bash" else None
    except (ValueError, KeyError, TypeError) as error:
        raise HookError(f"opscout push guard: the hook event cannot be read ({error})") from None
    if tool != "Bash":
        return ""
    if not isinstance(command, str):
        raise HookError("opscout push guard: the Bash event holds no command")
    read = read_command(command)
    if read is None:
        return ""
    if isinstance(read, PushCommand):
        read = _decide(read, Path(str(event.get("cwd") or ".")), location)
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": read.verdict,
                "permissionDecisionReason": read.reason,
            }
        }
    )


def _decide(push: PushCommand, cwd: Path, location: ConfigLocation) -> PushDecision:
    directory = cwd / Path(push.directory).expanduser() if push.directory else cwd
    current = _git(directory, "symbolic-ref", "--short", "-q", "HEAD")
    remote = push.remote or _remote_for(directory, current)
    default = _git(directory, "symbolic-ref", "--short", "-q", f"refs/remotes/{remote}/HEAD")
    if default is not None:
        default = default.removeprefix(f"{remote}/")
    upstream = _git(directory, "config", f"branch.{current}.merge") if current else None
    config = PushConfig(
        push_default=_git(directory, "config", "push.default") or "simple",
        remote_push=tuple(
            (_git(directory, "config", "--get-all", f"remote.{remote}.push") or "").split()
        ),
        upstream=upstream.removeprefix("refs/heads/") if upstream else None,
    )
    ship, readable = _ship(location)
    decision = decide_push(
        replace(push, remote=remote),
        current=current,
        default=default,
        patterns=ship.protected_branches,
        config=config,
    )
    if not readable and decision.verdict == "ask":
        note = " (the configured protected branches could not be read)"
        return PushDecision("ask", decision.reason.removesuffix("?") + note + "?")
    return decision


def _remote_for(directory: Path, current: str | None) -> str:
    """Return the remote a push without one goes to, as git chooses it."""
    candidates = [f"branch.{current}.pushRemote"] if current else []
    candidates.append("remote.pushDefault")
    if current:
        candidates.append(f"branch.{current}.remote")
    for key in candidates:
        if value := _git(directory, "config", key):
            return value
    return DEFAULT_REMOTE


def _ship(location: ConfigLocation) -> tuple[Ship, bool]:
    """Return the configured conventions, or the defaults and False when they cannot be read."""
    try:
        return load_config(location.directory).ship, True
    except ConfigError as error:
        # Nothing configured is fine; a configuration that exists but cannot be read is not.
        nothing_configured = isinstance(error, ConfigLocationError) and "no such" in str(error)
        return Ship(), nothing_configured


def _git(directory: Path, *args: str) -> str | None:
    program = shutil.which("git")
    if program is None:
        raise HookError("opscout push guard: git is not on PATH")
    result = subprocess.run(  # noqa: S603  (a fixed git command)
        [program, "-C", str(directory), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def session_start(
    location: ConfigLocation,
    environ: Mapping[str, str],
    home: Path,
    now: datetime,
    zone: tzinfo | None = None,
) -> str:
    """Return the SessionStart hook's output: the SSO warning, then the job notices (spec 007).

    Nothing when neither has anything to say.
    """
    settings, note = sso_settings(location)
    warning = render_warning(check_sessions(settings, environ, home, now), zone, note)
    jobs = job_notices(location, now.astimezone(zone))
    message = "\n\n".join(part for part in (warning, jobs) if part)
    if not message:
        return ""
    return json.dumps(
        {
            "systemMessage": message,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message},
        }
    )


def could_not_run(error: Exception) -> str:
    """Return the SessionStart output that says the session checks could not run, and why.

    An unexpected error is named by its type only: its text could quote what was being read.
    """
    if isinstance(error, AwsConfigError):
        return json.dumps({"systemMessage": f"opscout: the SSO check could not run: {error}"})
    return json.dumps(
        {"systemMessage": f"opscout: the session checks could not run ({type(error).__name__})"}
    )
