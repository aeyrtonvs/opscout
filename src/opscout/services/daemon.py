# SPDX-License-Identifier: Apache-2.0
"""Run jobs once per period, check model runs, and describe the schedule (spec 007).

Everything here works through the ports of ``opscout.core.daemon``; the adapters are built
by ``opscout.entrypoints.daemon``.
"""

import hashlib
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Final

from opscout.core.chat import GatewayStatus, MessageRef
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
    Receipt,
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
    alert: Callable[[str, str, str], MessageRef | None] | None = None
    """Sends the notice of a failed run (spec 008, FR-024); None without chat."""


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
        outcome, reason, receipt, facts = _decide(start, ports, held, key, period, run_id)
        chat = receipt.chat if receipt else None
        if outcome == "failed" and ports.alert is not None and not _own_delivery(reason):
            chat = _alert(ports.alert, start.job.name, run_id, period, reason)
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
            delivery=receipt.location if receipt else None,
            chat=chat,
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


_Decision = tuple[Outcome, str | None, Receipt | None, RunnerFacts | None]


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
        ports.delivery.preflight()
    except DeliveryError as error:
        return "failed", f"{DELIVERY_FAILED}{error}", None, None
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
            kept = Receipt(error.location) if error.location else None
            return "failed", f"{DELIVERY_FAILED}{error}", kept, result.facts
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
        kept = Receipt(error.location) if error.location else None
        return outcome, f"{reason} (the notice could not be delivered: {error})", kept, result.facts
    return outcome, reason, delivery, result.facts


DELIVERY_FAILED: Final = "delivery failed: "


def _own_delivery(reason: str | None) -> bool:
    """Return whether a failure was the delivery's own: then no notice could reach anyone."""
    return reason is not None and reason.startswith(DELIVERY_FAILED)


def _alert(
    alert: Callable[[str, str, str], MessageRef | None],
    job: str,
    run_id: str,
    period: str,
    reason: str | None,
) -> MessageRef | None:
    """Send a failed run's short notice (spec 008, FR-024); its failure changes nothing."""
    text = "\n".join(
        [
            f"# opscout {job}, {period}: failed",
            "",
            reason or "The run failed.",
            "",
            f"See the runs with: opscout daemon runs {job}",
            "",
        ]
    )
    try:
        return alert(job, run_id, text)
    except Exception:  # the run already failed; the notice is a courtesy
        return None


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
    """Return the enabled jobs, and the gateway when chat is on, as the scheduler should run
    them (FR-010; spec 008, FR-013)."""
    jobs = [
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
    if daemon.chat is not None:
        # The gateway reads its configuration once, at start; a change of the chat setting
        # changes this fingerprint, so install reloads it (independent review).
        setting = daemon.chat.model_dump_json() + repr(sorted(daemon.secrets.items()))
        fingerprint = hashlib.sha256(setting.encode("utf-8")).hexdigest()[:12]
        jobs.append(
            ScheduledJob(
                name=GATEWAY,
                arguments=(*command, "gateway", "--config", str(config)),
                times=(),
                log=logs / f"{GATEWAY}.log",
                environment=MappingProxyType({"PATH": path, "OPSCOUT_CHAT_SETTING": fingerprint}),
                keep_alive=True,
            )
        )
    return jobs


GATEWAY: Final = "gateway"
"""The gateway's name as a scheduled entry (spec 008); no job may take it."""


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
    if change.note is not None:
        return f"{change.action} {change.label} ({change.note})"
    if change.action in ("add", "update") and change.job is not None and change.job.keep_alive:
        return f"{change.action} {change.label} (always)"
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


@dataclass(frozen=True)
class GatewayView:
    """What status knows of the gateway: whether chat is on, its last state, its log."""

    configured: bool
    status: GatewayStatus | None
    log: Path
    now: datetime | None = None
    """The time to judge staleness by; status passes it, the session notice has its own."""


_GATEWAY_STATES: Final = {
    "add": "not installed",
    "remove": "installed but chat is not configured",
    "update": "differs from the configuration",
    "load": "not loaded",
}


def render_status(
    configured: Mapping[str, JobSettings],
    installed: Sequence[InstalledJob],
    pending: PendingSchedule,
    last: Mapping[str, RunRecord | None],
    engine_version: str,
    exists: Callable[[str], bool],
    gateway: GatewayView | None = None,
) -> str:
    """Return ``opscout daemon status``: one line per configured or installed job (FR-012),
    then the gateway's when chat is configured or it is installed (spec 008, FR-020)."""
    by_name = {job.name: job for job in installed}
    changes = {change.label.removeprefix(LABEL_PREFIX): change for change in pending.changes}
    names = sorted((set(configured) | set(by_name)) - {GATEWAY})
    chat_line = _gateway_line(gateway, by_name, changes) if gateway is not None else None
    if not names and chat_line is None:
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
    if chat_line is not None:
        lines.append(chat_line)
    return "\n".join(lines) + "\n"


def _gateway_line(
    view: GatewayView, installed: Mapping[str, InstalledJob], changes: Mapping[str, SchedulerChange]
) -> str | None:
    if not view.configured and GATEWAY not in installed:
        return None
    change = changes.get(GATEWAY)
    if change is not None and change.action != "restart":
        state = f"{_GATEWAY_STATES[change.action]} (run opscout daemon install)"
        return f"{GATEWAY}  always  {state}"
    status = view.status
    see = f"see {view.log}"
    if status is None:
        connection = f"never connected ({see})"
    elif status.state == "stopped":
        connection = (
            f"stopped: {status.reason}; last seen {status.last_seen:%Y-%m-%d %H:%M} "
            f"(run opscout daemon install to start it again; {see})"
        )
    elif status.state == "connecting":
        connection = f"not connected since {status.since:%Y-%m-%d %H:%M} ({see})"
    elif view.now is not None and view.now - status.last_seen > GRACE:
        connection = f"not running; last seen {status.last_seen:%Y-%m-%d %H:%M} ({see})"
    else:
        connection = f"connected since {status.since:%Y-%m-%d %H:%M}"
    return f"{GATEWAY}  always  installed, loaded  {connection}"


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
    gateway: GatewayView | None = None,
) -> str | None:
    """Return the SessionStart lines about jobs needing attention, or None (FR-028), and
    about the gateway when chat is configured (spec 008, FR-021).

    ``installed`` is None where no scheduler exists; then nothing is said about what is not
    installed, nor about the gateway, which only a scheduler keeps running.
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
    if gateway is not None and gateway.configured and installed is not None:
        line = _gateway_notice(gateway, installed.get(GATEWAY), now)
        if line is not None:
            lines.append(line)
    if not lines:
        return None
    return "\n".join(["opscout scheduled jobs:", *lines])


def _gateway_notice(view: GatewayView, installed_at: datetime | None, now: datetime) -> str | None:
    if installed_at is None:
        return f"- {GATEWAY}: not installed (run opscout daemon install)"
    see = f"(see {view.log})"
    status = view.status
    if status is None:
        return f"- {GATEWAY}: never connected {see}" if now - installed_at > GRACE else None
    if status.state == "stopped":
        return (
            f"- {GATEWAY}: stopped: {status.reason} (run opscout daemon install to start it again)"
        )
    if status.state == "connecting" and now - status.since > GRACE:
        return f"- {GATEWAY}: not connected since {status.since:%Y-%m-%d %H:%M} {see}"
    if now - status.last_seen > GRACE:
        return f"- {GATEWAY}: not running since {status.last_seen:%Y-%m-%d %H:%M} {see}"
    return None
