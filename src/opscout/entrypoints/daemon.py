# SPDX-License-Identifier: Apache-2.0
"""The daemon's composition root and commands (spec 007, ADR-0011, ADR-0021).

This is the only module that builds adapters (FR-025): ``wiring()`` returns the real ones,
and tests replace it with fakes. The commands here are what ``opscout run``, ``opscout
daemon …`` and ``opscout secret …`` do; ``opscout.entrypoints.cli`` only parses arguments.
"""

import getpass
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import platformdirs

import opscout
from opscout import __version__
from opscout.adapters.claude_cli import ClaudeCliRunner
from opscout.adapters.keychain import KeyringSecretStore
from opscout.adapters.launchd import Launchctl, LaunchdScheduler
from opscout.adapters.run_files import FileRunStore, LocalOutbox
from opscout.core.config import (
    JOB_NAMES,
    KEYCHAIN_ITEMS,
    ConfigError,
    ConfigLocationError,
    Configuration,
    Daemon,
    InvalidConfigError,
    JobSettings,
    KeychainRef,
)
from opscout.core.daemon import (
    JOBS,
    SUCCESS,
    Delivery,
    PendingSchedule,
    RecordError,
    Runner,
    RunStore,
    Scheduler,
    SchedulerError,
    SecretError,
    SecretStore,
    StoreError,
    Trigger,
)
from opscout.entrypoints.config import load_config
from opscout.services.config import ConfigLocation, resolve_config_dir
from opscout.services.confirm import schedule_code
from opscout.services.daemon import (
    Ports,
    Start,
    compare_profile,
    describe_change,
    render_outcome,
    render_runs,
    render_status,
    resolve_profile,
    run_job,
    session_notices,
    wanted_jobs,
)


@dataclass(frozen=True)
class Directories:
    """Where the engine keeps its state, logs and caches (ADR-0021 rule 3)."""

    data: Path
    log: Path
    cache: Path


@dataclass(frozen=True)
class Wiring:
    """Every adapter and host fact the commands use."""

    directories: Directories
    environ: Mapping[str, str]
    clock: Callable[[], datetime]
    runner: Callable[[Daemon, Path], Runner]
    store: RunStore
    delivery: Delivery
    secrets: SecretStore
    scheduler: Scheduler | None
    engine_command: Callable[[], list[str]]
    path_exists: Callable[[str], bool]
    is_terminal: Callable[[], bool]
    ask: Callable[[str], str]
    read_secret: Callable[[str], str]
    which: Callable[[str, str], str | None]
    """Find a program on a search path."""


def engine_command(package: Path, version: str, which: Callable[[str], str | None]) -> list[str]:
    """Return the absolute command that starts this engine, as the launcher would (R6).

    From a clone, ``uv run`` on the clone; from a release, ``uvx`` on exactly this version.
    Raises ``LookupError`` when the program is missing.
    """
    root = package.parents[2]
    pyproject = root / "pyproject.toml"
    in_clone = (root / "src" / "opscout").is_dir() and pyproject.is_file()
    if in_clone and 'name = "opscout"' in pyproject.read_text(encoding="utf-8"):
        program = which("uv")
        if program is None:
            raise LookupError("uv is required to schedule jobs: https://docs.astral.sh/uv/")
        return [program, "run", "--quiet", "--frozen", "--project", str(root), "opscout"]
    program = which("uvx")
    if program is None:
        raise LookupError("uvx is required to schedule jobs: https://docs.astral.sh/uv/")
    return [program, "--quiet", "--from", f"opscout=={version}", "opscout"]


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def wiring() -> Wiring:
    """Return the real adapters: the only place they are built (FR-025)."""
    directories = Directories(
        data=Path(platformdirs.user_data_dir("opscout", appauthor=False)),
        log=Path(platformdirs.user_log_dir("opscout", appauthor=False)),
        cache=Path(platformdirs.user_cache_dir("opscout", appauthor=False)),
    )
    environ = os.environ
    scheduler: Scheduler | None = None
    if sys.platform == "darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        scheduler = LaunchdScheduler(agents, Launchctl(os.getuid()))

    def runner(daemon: Daemon, run_dir: Path) -> Runner:
        return ClaudeCliRunner(daemon.claude_path, run_dir, environ, compare_profile)

    return Wiring(
        directories=directories,
        environ=environ,
        clock=lambda: datetime.now().astimezone(),
        runner=runner,
        store=FileRunStore(directories.data),
        delivery=LocalOutbox(directories.data),
        secrets=KeyringSecretStore(),
        scheduler=scheduler,
        engine_command=lambda: engine_command(Path(opscout.__file__), __version__, shutil.which),
        path_exists=lambda path: Path(path).exists(),
        is_terminal=lambda: sys.stdin.isatty() and sys.stdout.isatty(),
        ask=_ask,
        read_secret=getpass.getpass,
        which=lambda name, search: shutil.which(name, path=search),
    )


class CommandError(Exception):
    """A command cannot start; the message says why (exit 2)."""


def _configuration(flag: Path | None, environ: Mapping[str, str]) -> tuple[Configuration, Path]:
    location = resolve_config_dir(flag, environ, Path.home())
    try:
        return load_config(location.directory), location.directory.absolute()
    except InvalidConfigError as error:
        raise CommandError(
            f"the configuration has {len(error.problems)} problem(s); run opscout config validate"
        ) from None
    except ConfigLocationError as error:
        raise CommandError(str(error)) from None


def _settings(daemon: Daemon) -> dict[str, JobSettings]:
    return {str(name): settings for name, settings in daemon.jobs.items()}


def _fail(command: str, reason: str) -> int:
    sys.stderr.write(f"opscout {command}: {reason}\n")
    return 2


def run_command(job_name: str, *, force: bool, trigger: Trigger, flag: Path | None) -> int:
    """Run one job for the current period (``opscout run``): 0, 1 or 2 (research R13)."""
    wired = wiring()
    try:
        configuration, _ = _configuration(flag, wired.environ)
    except CommandError as error:
        return _fail("run", str(error))
    daemon = configuration.daemon
    job = JOBS.get(job_name)
    if job is None:
        configured = ", ".join(daemon.jobs) or f"none (the engine's jobs: {', '.join(JOB_NAMES)})"
        return _fail("run", f'unknown job "{job_name}"; configured jobs: {configured}')
    start = Start(
        job=job,
        profile=resolve_profile(job, _settings(daemon).get(job_name), daemon),
        secrets=dict(daemon.secrets.items()),
        trigger=trigger,
        force=force,
        engine_version=__version__,
    )
    ports = Ports(
        runner=wired.runner(daemon, wired.directories.cache / "run"),
        store=wired.store,
        delivery=wired.delivery,
        secrets=wired.secrets,
        clock=wired.clock,
    )
    try:
        record = run_job(start, ports)
    except RecordError as error:
        sys.stderr.write(f"opscout run: {error}\n")
        return 1
    except StoreError as error:
        return _fail("run", f"the run store cannot be used: {error}")
    print(render_outcome(record))
    return 0 if record.outcome in SUCCESS else 1


NO_SCHEDULER = "no scheduler is available for this system (only launchd, on macOS)"
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


def job_path(wired: Wiring, daemon: Daemon, command: list[str]) -> str:
    """Return the PATH an installed job gets: the directories of Claude Code, node and the
    engine's program, then the system's (research R5). It does not depend on the shell
    that installs, so installing from another terminal changes nothing."""
    search = wired.environ.get("PATH", "")
    claude = daemon.claude_path or wired.which("claude", search)
    programs = [claude, wired.which("node", search), command[0]]
    directories = [str(Path(program).parent) for program in programs if program]
    return ":".join(dict.fromkeys([*directories, *SYSTEM_PATH]))


def _flags(flag: Path | None) -> str:
    return f" --config {shlex.quote(str(flag))}" if flag else ""


def schedule_command(
    *, uninstall: bool, dry_run: bool, confirm: str | None, flag: Path | None
) -> int:
    """Install or uninstall the scheduled jobs after confirmation (FR-009, FR-011, FR-029)."""
    command = "daemon uninstall" if uninstall else "daemon install"
    wired = wiring()
    configured: dict[str, JobSettings] = {}
    wanted = []
    if wired.scheduler is None:
        return _fail(command, NO_SCHEDULER)
    scheduler = wired.scheduler
    if not uninstall:
        try:
            configuration, directory = _configuration(flag, wired.environ)
            configured = _settings(configuration.daemon)
            command_line = wired.engine_command()
            wanted = wanted_jobs(
                configuration.daemon,
                command_line,
                config=directory,
                logs=wired.directories.log,
                path=job_path(wired, configuration.daemon, command_line),
            )
        except (CommandError, LookupError) as error:
            return _fail(command, str(error))
    try:
        pending = scheduler.plan(wanted)
    except SchedulerError as error:
        return _fail(command, str(error))
    if not pending.changes:
        print("Nothing to uninstall." if uninstall else "Scheduled jobs are up to date.")
        return 0
    for change in pending.changes:
        print(describe_change(change, configured))
    code = schedule_code(pending)
    if confirm is not None and not dry_run:
        if confirm.strip().lower() != code:
            print(
                "The configuration or the installed jobs changed since that code; run "
                f"opscout {command} --dry-run again."
            )
            return 1
        return _apply(command, wired, pending)
    if not dry_run and wired.is_terminal():
        answer = wired.ask("Apply these changes to your scheduled jobs? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 1
        try:
            again = scheduler.plan(wanted)
        except SchedulerError as error:
            return _fail(command, str(error))
        if schedule_code(again) != code:
            print(
                "The configuration or the installed jobs changed while you were asked; nothing "
                f"was changed. Run opscout {command} again."
            )
            return 1
        return _apply(command, wired, pending)
    print(f"\nConfirmation code: {code}")
    print(f"To apply it: opscout {command}{_flags(flag)} --confirm {code}")
    return 1


def _apply(command: str, wired: Wiring, pending: PendingSchedule) -> int:
    if wired.scheduler is None:  # checked by the caller
        return _fail(command, NO_SCHEDULER)
    try:
        wired.directories.log.mkdir(parents=True, exist_ok=True)
        wired.scheduler.apply(pending)
    except (SchedulerError, OSError) as error:
        return _fail(command, str(error))
    actions = [change.action for change in pending.changes]
    summary = (
        f"Installed {actions.count('add')}, updated {actions.count('update')}, "
        f"removed {actions.count('remove')}"
    )
    loaded = actions.count("load")
    print(summary + (f", loaded {loaded}." if loaded else "."))
    return 0


def status_command(flag: Path | None) -> int:
    """List the configured and installed jobs, their mismatches and last outcome (FR-012)."""
    wired = wiring()
    if wired.scheduler is None:
        return _fail("daemon status", NO_SCHEDULER)
    try:
        configuration, directory = _configuration(flag, wired.environ)
        command_line = wired.engine_command()
        wanted = wanted_jobs(
            configuration.daemon,
            command_line,
            config=directory,
            logs=wired.directories.log,
            path=job_path(wired, configuration.daemon, command_line),
        )
        installed = wired.scheduler.installed()
        pending = wired.scheduler.plan(wanted)
    except (CommandError, LookupError, SchedulerError) as error:
        return _fail("daemon status", str(error))
    configured = _settings(configuration.daemon)
    names = set(configured) | {job.name for job in installed}
    last = {name: next(iter(wired.store.records(name, 1)), None) for name in names}
    sys.stdout.write(
        render_status(configured, installed, pending, last, __version__, wired.path_exists)
    )
    return 0


def runs_command(job: str | None, limit: int) -> int:
    """List recent run records, newest first (FR-022)."""
    if limit < 1:
        return _fail("daemon runs", "--limit must be at least 1")
    sys.stdout.write(render_runs(wiring().store.records(job, limit)))
    return 0


def secret_set_command(name: str, flag: Path | None) -> int:
    """Store a configured secret, read without echo (FR-024)."""
    command = "secret set"
    wired = wiring()
    if name not in KEYCHAIN_ITEMS:
        return _fail(command, f'unknown secret "{name}"; known: {", ".join(KEYCHAIN_ITEMS)}')
    try:
        configuration, _ = _configuration(flag, wired.environ)
    except CommandError as error:
        return _fail(command, str(error))
    ref = {str(k): v for k, v in configuration.daemon.secrets.items()}.get(name)
    if ref is None:
        return _fail(
            command,
            f"add daemon.secrets.{name} (a keychain service, and optionally an account) to "
            "the configuration first",
        )
    if wired.is_terminal():
        value = wired.read_secret(f"Value for {name} (not shown): ")
    else:
        value = sys.stdin.readline().rstrip("\r\n")
    if not value.strip():
        return _fail(command, "no value was given; nothing was stored")
    try:
        wired.secrets.store(name, ref, value)
    except SecretError as error:
        return _fail(command, str(error))
    print(f"Stored {name} in the keychain (service {ref.service}, account {_account(ref)}).")
    return 0


def _account(ref: KeychainRef) -> str:
    return ref.account or "opscout"


def secret_check_command(name: str | None, flag: Path | None) -> int:
    """Say whether each configured secret is in the keychain, never its value (FR-024)."""
    command = "secret check"
    wired = wiring()
    if name is not None and name not in KEYCHAIN_ITEMS:
        return _fail(command, f'unknown secret "{name}"; known: {", ".join(KEYCHAIN_ITEMS)}')
    try:
        configuration, _ = _configuration(flag, wired.environ)
    except CommandError as error:
        return _fail(command, str(error))
    references = {str(k): v for k, v in configuration.daemon.secrets.items()}
    if name is not None and name not in references:
        return _fail(command, f"{name} is not in daemon.secrets in the configuration")
    chosen = [name] if name is not None else sorted(references)
    if not chosen:
        print("No secrets are configured.")
        return 0
    found = True
    for item in chosen:
        ref = references[item]
        status = wired.secrets.status(item, ref)
        detail = f"{status.reason}; " if status.reason else ""
        print(
            f"{item}: {status.state} ({detail}keychain service {ref.service}, "
            f"account {_account(ref)})"
        )
        found = found and status.state == "present"
    return 0 if found else 1


def job_notices(location: ConfigLocation, now: datetime) -> str | None:
    """Return the SessionStart lines about scheduled jobs, or None (FR-028).

    Reads only the configuration and the run records; never fails the hook.
    """
    try:
        daemon = load_config(location.directory).daemon
    except ConfigError:
        return None  # the SSO check already says what is wrong with the configuration
    if not any(settings.enabled for settings in daemon.jobs.values()):
        return None
    try:
        wired = wiring()
        records = {str(name): wired.store.records(name, 100) for name in daemon.jobs}
        installed = wired.scheduler.installed_times() if wired.scheduler else None
    except Exception as error:  # the session start is never blocked (spec 005)
        return f"opscout scheduled jobs: could not be checked ({type(error).__name__})"
    return session_notices(daemon, records, installed, now)
