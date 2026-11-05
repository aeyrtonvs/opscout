# SPDX-License-Identifier: Apache-2.0
"""LaunchdScheduler: the user's launchd agents, behind a seam (spec 007, research R5).

Each job is a property list ``opscout.<job>.plist`` in the agents directory
(``~/Library/LaunchAgents``, given by the composition root). Only files whose name starts
with ``opscout.`` are read or changed. A job is up to date when its file holds exactly the
bytes this module renders and launchd has it loaded; then nothing is written or reloaded
(FR-009). launchd is reached through ``ServiceManager``; ``Launchctl`` runs
``/bin/launchctl`` and tests replace it (FR-013).
"""

import contextlib
import os
import plistlib
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol

from opscout.core.daemon import (
    LABEL_PREFIX,
    InstalledJob,
    PendingSchedule,
    ScheduledJob,
    SchedulerChange,
    SchedulerError,
)

LAUNCHCTL: Final = "/bin/launchctl"


class ServiceManager(Protocol):
    """The seam between the adapter and launchd (FR-013)."""

    def load(self, plist: Path) -> None:
        """Load a job from its property list."""
        ...

    def unload(self, label: str) -> None:
        """Unload a job if it is loaded."""
        ...

    def is_loaded(self, label: str) -> bool:
        """Return whether launchd has the job loaded."""
        ...


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


class Launchctl:
    """``ServiceManager`` on ``/bin/launchctl``, in the user's GUI domain."""

    def __init__(
        self, uid: int, run: Callable[[list[str]], "subprocess.CompletedProcess[str]"] = _run
    ) -> None:
        self._domain = f"gui/{uid}"
        self._run = run

    def load(self, plist: Path) -> None:
        """Bootstrap the job. Raises ``SchedulerError``."""
        result = self._run([LAUNCHCTL, "bootstrap", self._domain, str(plist)])
        if result.returncode != 0:
            raise SchedulerError(f"launchctl bootstrap {plist.name}: {_said(result)}")

    def unload(self, label: str) -> None:
        """Boot the job out if it is loaded. Raises ``SchedulerError``."""
        if not self.is_loaded(label):
            return
        result = self._run([LAUNCHCTL, "bootout", f"{self._domain}/{label}"])
        if result.returncode != 0:
            raise SchedulerError(f"launchctl bootout {label}: {_said(result)}")

    def is_loaded(self, label: str) -> bool:
        """Return whether launchd has the job loaded."""
        return self._run([LAUNCHCTL, "print", f"{self._domain}/{label}"]).returncode == 0


def _said(result: "subprocess.CompletedProcess[str]") -> str:
    text = (result.stderr or result.stdout or "").strip().splitlines()
    return f"exit {result.returncode}" + (f" ({text[0][:200]})" if text else "")


def plist_bytes(job: ScheduledJob) -> bytes:
    """Return the job's property list; the same job always gives the same bytes."""
    data: dict[str, Any] = {
        "Label": job.label,
        "ProgramArguments": list(job.arguments),
        "StartCalendarInterval": sorted(
            ({"Hour": hour, "Minute": minute, "Weekday": weekday % 7}
             for weekday, hour, minute in job.times),
            key=lambda entry: (entry["Weekday"], entry["Hour"], entry["Minute"]),
        ),
        "StandardOutPath": str(job.log),
        "StandardErrorPath": str(job.log),
        "EnvironmentVariables": dict(job.environment),
        "ProcessType": "Background",
    }  # fmt: skip
    return plistlib.dumps(data, sort_keys=True)


class LaunchdScheduler:
    """The ``Scheduler`` port on launchd user agents."""

    def __init__(self, agents: Path, manager: ServiceManager) -> None:
        self._agents = agents
        self._manager = manager

    def _files(self) -> list[Path]:
        try:
            return sorted(self._agents.glob(f"{LABEL_PREFIX}*.plist"))
        except OSError as error:
            raise SchedulerError(f"{self._agents}: cannot be read ({error.strerror})") from None

    def installed(self) -> list[InstalledJob]:
        """Return every ``opscout.*`` job, with whether launchd has it loaded."""
        found = []
        for path in self._files():
            content = path.read_bytes()
            try:
                arguments = tuple(str(a) for a in plistlib.loads(content)["ProgramArguments"])
            except (plistlib.InvalidFileException, KeyError, TypeError, ValueError):
                arguments = ()
            found.append(
                InstalledJob(
                    label=path.stem,
                    path=path,
                    content=content,
                    loaded=self._manager.is_loaded(path.stem),
                    arguments=arguments,
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
                )
            )
        return found

    def installed_times(self) -> dict[str, datetime]:
        """Return each installed job's name and file time, without asking launchd."""
        return {
            path.stem.removeprefix(LABEL_PREFIX): datetime.fromtimestamp(
                path.stat().st_mtime
            ).astimezone()
            for path in self._files()
        }

    def plan(self, wanted: Sequence[ScheduledJob]) -> PendingSchedule:
        """Return the changes that make the ``opscout.*`` jobs exactly the wanted ones."""
        current = {job.label: job for job in self.installed()}
        by_label = {job.label: job for job in wanted}
        changes = []
        for label in sorted(set(current) | set(by_label)):
            job, installed = by_label.get(label), current.get(label)
            if job is None:
                if installed is not None:
                    changes.append(SchedulerChange("remove", label, installed.content, None))
                continue
            new = plist_bytes(job)
            if installed is None:
                changes.append(SchedulerChange("add", label, None, new, job))
            elif installed.content != new:
                changes.append(SchedulerChange("update", label, installed.content, new, job))
            elif not installed.loaded:
                changes.append(SchedulerChange("load", label, installed.content, new, job))
        return PendingSchedule(tuple(changes))

    def apply(self, pending: PendingSchedule) -> None:
        """Apply the changes in order. Raises ``SchedulerError``."""
        for change in pending.changes:
            path = self._agents / f"{change.label}.plist"
            if change.action != "load":
                # Also before an add: a job may be loaded with its file gone.
                self._manager.unload(change.label)
            if change.action == "remove":
                path.unlink(missing_ok=True)
                continue
            if change.action in ("add", "update") and change.new is not None:
                self._write(path, change.new)
            self._manager.load(path)

    def _write(self, path: Path, data: bytes) -> None:
        try:
            self._agents.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self._agents, prefix=f".{path.name}.")
        except OSError as error:
            raise SchedulerError(f"{path}: cannot be written ({error.strerror})") from None
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            Path(temporary).chmod(0o644)
            Path(temporary).replace(path)
        except OSError as error:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
            raise SchedulerError(f"{path}: cannot be written ({error.strerror})") from None
