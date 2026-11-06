# SPDX-License-Identifier: Apache-2.0
"""In-memory fakes of the daemon ports, a scripted runner and a fixed clock (spec 007)."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opscout.core.config import KeychainRef
from opscout.core.daemon import (
    DeliveryError,
    DeliveryKind,
    InstalledJob,
    PendingSchedule,
    Receipt,
    RunProfile,
    RunRecord,
    RunResult,
    ScheduledJob,
    SchedulerChange,
    SecretError,
    SecretStatus,
)

ZONE = timezone(timedelta(hours=1))
START = datetime(2026, 11, 5, 9, 30, tzinfo=ZONE)
SENTINEL = "sentinel-secret-value-0123456789"
"""A secret value searched for in every output, log, record and outbox file (SC-004)."""


@dataclass
class Clock:
    """Returns the given times in turn, then keeps advancing by one second."""

    times: list[datetime] = field(default_factory=lambda: [START])
    calls: int = 0

    def __call__(self) -> datetime:
        if self.calls < len(self.times):
            value = self.times[self.calls]
        else:
            value = self.times[-1] + timedelta(seconds=self.calls - len(self.times) + 1)
        self.calls += 1
        return value


@dataclass
class ScriptedRunner:
    """Returns the scripted results in turn and records each call."""

    results: list[RunResult]
    calls: list[tuple[RunProfile, str, dict[str, str]]] = field(default_factory=list)

    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
        self.calls.append((profile, prompt, dict(env)))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


@dataclass
class MemoryRunStore:
    """Records in a list; a period in ``busy`` is held by another start."""

    saved: list[RunRecord] = field(default_factory=list)
    busy: set[tuple[str, str]] = field(default_factory=set)

    def hold(self, job: str, period: str) -> AbstractContextManager[bool]:
        @contextmanager
        def held() -> Iterator[bool]:
            if (job, period) in self.busy:
                yield False
                return
            self.busy.add((job, period))
            try:
                yield True
            finally:
                self.busy.discard((job, period))

        return held()

    def delivered(self, run_key: str) -> RunRecord | None:
        found = [r for r in self.saved if r.run_key == run_key and r.outcome == "delivered"]
        return max(found, key=lambda record: record.run_id) if found else None

    def write(self, record: RunRecord) -> None:
        self.saved.append(record)

    def records(self, job: str | None, limit: int) -> list[RunRecord]:
        chosen = [r for r in self.saved if job is None or r.job == job]
        return sorted(chosen, key=lambda record: record.run_id, reverse=True)[:limit]

    def get(self, job: str, run_id: str) -> RunRecord | None:
        found = [r for r in self.saved if r.job == job and r.run_id == run_id]
        return found[-1] if found else None


@dataclass
class MemoryDelivery:
    """Keeps each delivery; fails when ``broken``."""

    sent: list[tuple[str, str, DeliveryKind, str]] = field(default_factory=list)
    broken: bool = False

    unready: str | None = None

    def preflight(self) -> None:
        if self.unready is not None:
            raise DeliveryError(self.unready)

    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> Receipt:
        if self.broken:
            raise DeliveryError("the outbox cannot be written (PermissionError)")
        self.sent.append((job, run_id, kind, text))
        return Receipt(f"/example/outbox/{job}/{run_id}.md")


@dataclass
class MemorySecretStore:
    """Secrets by (service, account); every call fails when ``unavailable``."""

    values: dict[tuple[str, str], str] = field(default_factory=dict)
    unavailable: bool = False

    def _key(self, ref: KeychainRef) -> tuple[str, str]:
        return (ref.service, ref.account or "opscout")

    def status(self, name: str, ref: KeychainRef) -> SecretStatus:
        if self.unavailable:
            return SecretStatus("unavailable", "the keychain is locked")
        return SecretStatus("present" if self._key(ref) in self.values else "missing")

    def resolve(self, name: str, ref: KeychainRef) -> str:
        status = self.status(name, ref)
        if status.state != "present":
            raise SecretError(name, status)
        return self.values[self._key(ref)]

    def store(self, name: str, ref: KeychainRef, value: str) -> None:
        if self.unavailable:
            raise SecretError(name, SecretStatus("unavailable", "the keychain is locked"))
        self.values[self._key(ref)] = value


@dataclass
class MemoryScheduler:
    """Installed jobs by label; ``apply`` makes them the wanted ones."""

    jobs: dict[str, ScheduledJob] = field(default_factory=dict)
    loaded: set[str] = field(default_factory=set)
    times: dict[str, datetime] = field(default_factory=dict)
    applied: list[PendingSchedule] = field(default_factory=list)
    restarted: list[str] = field(default_factory=list)

    def installed(self) -> list[InstalledJob]:
        return [
            InstalledJob(
                label=label,
                path=Path(f"/example/{label}.plist"),
                content=repr(job).encode(),
                loaded=label in self.loaded,
                arguments=job.arguments,
                modified_at=self.times.get(job.name),
            )
            for label, job in sorted(self.jobs.items())
        ]

    def installed_times(self) -> dict[str, datetime]:
        return {job.name: self.times.get(job.name, START) for job in self.jobs.values()}

    def plan(self, wanted: Sequence[ScheduledJob]) -> PendingSchedule:
        changes = []
        by_label = {job.label: job for job in wanted}
        for label in sorted(set(by_label) | set(self.jobs)):
            new, current = by_label.get(label), self.jobs.get(label)
            new_bytes = repr(new).encode() if new else None
            current_bytes = repr(current).encode() if current else None
            if new is None:
                changes.append(SchedulerChange("remove", label, current_bytes, None))
            elif current is None:
                changes.append(SchedulerChange("add", label, None, new_bytes, new))
            elif new != current:
                changes.append(SchedulerChange("update", label, current_bytes, new_bytes, new))
            elif label not in self.loaded:
                changes.append(SchedulerChange("load", label, current_bytes, new_bytes, new))
        return PendingSchedule(tuple(changes))

    def apply(self, pending: PendingSchedule) -> None:
        self.applied.append(pending)
        for change in pending.changes:
            if change.action == "restart":
                self.restarted.append(change.label)
                continue
            if change.action == "remove":
                self.jobs.pop(change.label, None)
                self.loaded.discard(change.label)
            else:
                assert change.job is not None
                self.jobs[change.label] = change.job
                self.loaded.add(change.label)
