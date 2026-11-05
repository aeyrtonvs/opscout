# SPDX-License-Identifier: Apache-2.0
"""Run jobs once per period, check model runs, and describe the schedule (spec 007).

Everything here works through the ports of ``opscout.core.daemon``; the adapters are built
by ``opscout.entrypoints.daemon``.
"""

import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Final

from opscout.core.config import WEEKDAYS, Daemon, JobSettings, KeychainRef
from opscout.core.daemon import (
    LABEL_PREFIX,
    MINIMUM_CLAUDE_CODE,
    TOKEN_VARIABLE,
    Delivery,
    DeliveryError,
    InstalledJob,
    Job,
    Outcome,
    PendingSchedule,
    RecordError,
    Runner,
    RunnerFacts,
    RunProfile,
    RunRecord,
    RunStore,
    ScheduledJob,
    SchedulerChange,
    SecretError,
    SecretStore,
    StartupReport,
    StoreError,
    Trigger,
)


def period_of(now: datetime) -> str:
    """Return a daily job's period: the local date at start, computed once (FR-003)."""
    return now.date().isoformat()


def run_key(job: str, period: str) -> str:
    """Return the key that decides whether a period already delivered (FR-003)."""
    return f"{job}:{period}"


def resolve_profile(job: Job, settings: JobSettings | None, daemon: Daemon) -> RunProfile:
    """Return the job's profile with the configured limits and secrets (FR-001)."""
    base = job.profile
    secrets = {TOKEN_VARIABLE: "claude_token"} if "claude_token" in daemon.secrets else {}
    return RunProfile(
        tools=base.tools,
        mcp_servers=base.mcp_servers,
        model=settings.model if settings and settings.model else base.model,
        budget_usd=settings.budget_usd if settings and settings.budget_usd else base.budget_usd,
        max_turns=settings.max_turns if settings and settings.max_turns else base.max_turns,
        output=base.output,
        secrets=MappingProxyType({**base.secrets, **secrets}),
    )


@dataclass(frozen=True)
class Start:
    """One start of a job: what runs, for whom, and how it was triggered."""

    job: Job
    profile: RunProfile
    secrets: Mapping[str, KeychainRef]
    trigger: Trigger
    force: bool
    engine_version: str


@dataclass(frozen=True)
class Ports:
    """The ports a start goes through, and the clock (local, aware times)."""

    runner: Runner
    store: RunStore
    delivery: Delivery
    secrets: SecretStore
    clock: Callable[[], datetime]
    new_id: Callable[[datetime], str] = field(default=lambda moment: new_run_id(moment))


def new_run_id(moment: datetime) -> str:
    """Return a run id: the start time in UTC and six random hexadecimal characters."""
    return f"{moment.astimezone(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def run_job(start: Start, ports: Ports) -> RunRecord:
    """Run a job for its period at most once, and record the start (FR-003 to FR-006).

    Raises ``StoreError`` when the run store cannot be used: then nothing ran; and
    ``RecordError`` when the run ended but its record could not be written.
    """
    started = ports.clock()
    period = period_of(started)
    key = run_key(start.job.name, period)
    run_id = ports.new_id(started)
    with ports.store.hold(start.job.name, period) as held:
        outcome, reason, delivery, facts = _decide(start, ports, held, key, period, run_id)
        record = RunRecord(
            run_id=run_id,
            job=start.job.name,
            period=period,
            run_key=key,
            trigger=start.trigger,
            forced=start.force,
            engine_version=start.engine_version,
            outcome=outcome,
            reason=reason,
            started_at=started,
            ended_at=ports.clock(),
            delivery=delivery,
            runner=facts,
        )
        try:
            ports.store.write(record)
        except StoreError as error:
            raise RecordError(
                f"{render_outcome(record)}, but its record could not be written: {error}; "
                "the next start may deliver again"
            ) from None
    return record


_Decision = tuple[Outcome, str | None, str | None, RunnerFacts | None]


def _decide(
    start: Start, ports: Ports, held: bool, key: str, period: str, run_id: str
) -> _Decision:
    """Return the outcome, its reason, the delivery and the runner's facts."""
    if not held:
        return "skipped", "another start holds this period", None, None
    previous = ports.store.delivered(key)
    if previous is not None and not start.force:
        return "skipped", f"already delivered by run {previous.run_id}", None, None
    try:
        env = {
            variable: ports.secrets.resolve(name, start.secrets[name])
            for variable, name in start.profile.secrets.items()
        }
    except SecretError as error:
        return "failed", str(error), None, None
    try:
        result = ports.runner.run(start.profile, start.job.prompt, env)
    except Exception as error:  # every start that begins ends with a record (FR-006)
        return "failed", f"the runner failed ({type(error).__name__})", None, None
    finally:
        del env
    name = start.job.name
    if result.status == "ok" and result.facts is not None:
        text = start.job.render(result.output, result.facts, period)
        try:
            delivery = ports.delivery.deliver(name, run_id, "result", text)
        except DeliveryError as error:
            return "failed", f"delivery failed: {error}", None, result.facts
        return "delivered", None, delivery, result.facts
    if result.status in ("ok", "error"):
        return "failed", result.reason or "the run failed", None, result.facts
    if result.status == "refused":
        outcome: Outcome = "refused"
        reason = "; ".join(result.differences) or result.reason or "the start-up report differs"
        explanation = (
            "Claude Code started with more than the job's profile allows, so its output was "
            f"discarded: {reason}."
        )
    else:
        outcome = "inconclusive"
        reason = f"the output failed its schema twice: {result.reason}"
        explanation = f"The model's output did not pass the job's schema twice: {result.reason}."
    notice = "\n".join(
        [
            f"# opscout {name}, {period}: {outcome}",
            "",
            explanation,
            "",
            f"See the runs with: opscout daemon runs {name}",
            "",
        ]
    )
    try:
        delivery = ports.delivery.deliver(name, run_id, "notice", notice)
    except DeliveryError as error:
        return outcome, f"{reason} (the notice could not be delivered: {error})", None, result.facts
    return outcome, reason, delivery, result.facts


def render_outcome(record: RunRecord) -> str:
    """Return the one line ``opscout run`` prints (contracts/commands.md)."""
    head = f"{record.job} {record.period}: {record.outcome}"
    if record.outcome == "delivered":
        return f"{head} to {record.delivery}"
    return f"{head} ({record.reason})"


ALIASES: Final = ("haiku", "sonnet", "opus", "fable")


def compare_profile(
    profile: RunProfile, report: StartupReport, minimum: tuple[int, ...] = MINIMUM_CLAUDE_CODE
) -> tuple[str, ...]:
    """Return each way the start-up report differs from the profile; empty when it matches.

    The run is trusted only when this is empty (FR-015, research R2).
    """
    differences = []
    tools = sorted({*profile.tools, "StructuredOutput"})
    if sorted(report.tools) != tools:
        differences.append(f"tools: expected {_listed(tools)}, got {_listed(report.tools)}")
    if sorted(report.mcp_servers) != sorted(profile.mcp_servers):
        differences.append(
            f"tool servers: expected {_listed(profile.mcp_servers)}, "
            f"got {_listed(report.mcp_servers)}"
        )
    if report.permission_mode != "dontAsk":
        differences.append(f"permission mode: expected dontAsk, got {report.permission_mode}")
    alias = profile.model in ALIASES
    if (alias and not report.model.startswith(f"claude-{profile.model}-")) or (
        not alias and report.model != profile.model
    ):
        differences.append(f"model: expected {profile.model}, got {report.model}")
    if user := [name for name, path in report.plugins if path != "builtin"]:
        differences.append(f"plugins: expected only built-in plugins, got {', '.join(user)}")
    if _version(report.claude_code_version) < minimum:
        expected = ".".join(str(part) for part in minimum)
        differences.append(
            f"Claude Code version: expected {expected} or later, got {report.claude_code_version}"
        )
    return tuple(differences)


def _listed(names: Iterable[str]) -> str:
    return f"[{', '.join(sorted(names))}]"


def _version(text: str) -> tuple[int, ...]:
    """Return a version's numbers; one that cannot be read is older than any."""
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return ()


def wanted_jobs(
    daemon: Daemon, command: Sequence[str], *, config: Path, logs: Path, path: str
) -> list[ScheduledJob]:
    """Return the enabled jobs as the scheduler should run them (FR-010)."""
    return [
        ScheduledJob(
            name=name,
            arguments=(*command, "run", name, "--config", str(config), "--trigger", "scheduler"),
            times=tuple(
                (WEEKDAYS.index(day) + 1, *_clock_time(settings.at))
                for day in sorted(settings.weekdays, key=WEEKDAYS.index)
            ),
            log=logs / f"{name}.log",
            environment=MappingProxyType({"PATH": path}),
        )
        for name, settings in sorted(daemon.jobs.items())
        if settings.enabled
    ]


def _clock_time(at: str) -> tuple[int, int]:
    hour, minute = at.split(":")
    return int(hour), int(minute)


def describe_schedule(settings: JobSettings) -> str:
    """Return a job's schedule as ``09:30 mon to fri``."""
    days = sorted(settings.weekdays, key=WEEKDAYS.index)
    if len(days) == len(WEEKDAYS):
        return f"{settings.at} every day"
    indexes = [WEEKDAYS.index(day) for day in days]
    if len(days) > 2 and indexes == list(range(indexes[0], indexes[-1] + 1)):
        return f"{settings.at} {days[0]}\N{EN DASH}{days[-1]}"
    return f"{settings.at} {', '.join(days)}"


def describe_change(change: SchedulerChange, configured: Mapping[str, JobSettings]) -> str:
    """Return one line of an install's changes: ``add opscout.check (09:30 mon to fri)``."""
    settings = configured.get(change.label.removeprefix(LABEL_PREFIX))
    if change.action in ("add", "update") and settings is not None:
        return f"{change.action} {change.label} ({describe_schedule(settings)})"
    return f"{change.action} {change.label}"


def _stale(
    installed: InstalledJob, engine_version: str, exists: Callable[[str], bool]
) -> list[str]:
    """Return why an installed job would not start this engine (US2 scenario 7)."""
    reasons = []
    arguments = installed.arguments
    if arguments and not exists(arguments[0]):
        reasons.append(f"stale: {arguments[0]} is missing")
    if "--project" in arguments[:-1]:
        project = arguments[arguments.index("--project") + 1]
        if not exists(project):
            reasons.append(f"stale: {project} is missing")
    for argument in arguments:
        if argument.startswith("opscout==") and argument != f"opscout=={engine_version}":
            reasons.append(f"stale: installed with engine {argument.removeprefix('opscout==')}")
    return reasons


_STATES: Final = {
    "add": "not installed",
    "remove": "installed but not configured",
    "update": "schedule differs from the configuration",
    "load": "not loaded",
}


def render_status(
    configured: Mapping[str, JobSettings],
    installed: Sequence[InstalledJob],
    pending: PendingSchedule,
    last: Mapping[str, RunRecord | None],
    engine_version: str,
    exists: Callable[[str], bool],
) -> str:
    """Return ``opscout daemon status``: one line per configured or installed job (FR-012)."""
    by_name = {job.name: job for job in installed}
    changes = {change.label.removeprefix(LABEL_PREFIX): change for change in pending.changes}
    names = sorted(set(configured) | set(by_name))
    if not names:
        return "No jobs are configured or installed.\n"
    lines = []
    for name in names:
        settings = configured.get(name)
        schedule = describe_schedule(settings) if settings else "-"
        issues = []
        if settings is not None and not settings.enabled:
            issues.append("disabled but installed" if name in by_name else "disabled")
        elif name in changes:
            issues.append(_STATES[changes[name].action])
        if name in by_name:
            issues.extend(_stale(by_name[name], engine_version, exists))
        if not issues:
            state = "installed, loaded"
        elif issues == ["disabled"]:
            state = "disabled"
        else:
            state = "; ".join(issues) + " (run opscout daemon install)"
        record = last.get(name)
        when = f"{record.outcome} {record.started_at:%Y-%m-%d %H:%M}" if record else "none"
        lines.append(f"{name}  {schedule}  {state}  last: {when}")
    return "\n".join(lines) + "\n"


def render_runs(records: Sequence[RunRecord]) -> str:
    """Return ``opscout daemon runs``: one line per record, newest first (FR-022)."""
    if not records:
        return "No runs recorded.\n"
    lines = []
    for record in records:
        cost = f"{record.runner.cost_usd:.4f} USD" if record.runner else "-"
        seconds = (record.ended_at - record.started_at).total_seconds()
        lines.append(
            f"{record.run_id}  {record.job}  {record.period}  {record.trigger:<9}  "
            f"{record.outcome:<12}  {cost:<10}  {seconds:.1f} s"
        )
    return "\n".join(lines) + "\n"


GRACE: Final = timedelta(minutes=15)
"""How late a scheduled run may be before the session start reports it missing."""


def latest_slot(settings: JobSettings, now: datetime) -> datetime | None:
    """Return the most recent scheduled time at least ``GRACE`` before ``now``."""
    hour, minute = _clock_time(settings.at)
    days = ((now - timedelta(days=back)).date() for back in range(8))
    slots = (
        datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)
        for day in days
        if WEEKDAYS[day.weekday()] in settings.weekdays
    )
    return max((slot for slot in slots if slot <= now - GRACE), default=None)


_WORDING: Final = {"failed": "failed", "refused": "was refused", "inconclusive": "was inconclusive"}


def session_notices(
    daemon: Daemon,
    records: Mapping[str, Sequence[RunRecord]],
    installed: Mapping[str, datetime] | None,
    now: datetime,
) -> str | None:
    """Return the SessionStart lines about jobs needing attention, or None (FR-028).

    ``installed`` is None where no scheduler exists; then "not installed" is never said.
    """
    lines = []
    for name, settings in sorted(daemon.jobs.items()):
        if not settings.enabled:
            continue
        see = f"(see opscout daemon runs {name})"
        if installed is not None and name not in installed:
            lines.append(f"- {name}: configured but not installed (run opscout daemon install)")
            continue
        runs = [record for record in records.get(name, ()) if record.outcome != "skipped"]
        slot = latest_slot(settings, now)
        since = installed.get(name) if installed is not None else None
        if (
            slot is not None
            and since is not None
            and slot > since
            and not any(r.period == slot.date().isoformat() for r in records.get(name, ()))
        ):
            lines.append(f"- {name}: no run for its {settings.at} slot on {slot.date()} {see}")
        elif runs and runs[0].outcome in _WORDING:
            last = runs[0]
            lines.append(
                f"- {name}: the last run {_WORDING[last.outcome]} on "
                f"{last.started_at:%Y-%m-%d %H:%M} {see}"
            )
    if not lines:
        return None
    return "\n".join(["opscout scheduled jobs:", *lines])
