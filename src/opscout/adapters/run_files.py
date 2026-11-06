# SPDX-License-Identifier: Apache-2.0
"""The run store and the local outbox, as files under the data directory (spec 007).

Records live at ``<data>/runs/<job>/<run-id>.json`` and deliveries at
``<data>/outbox/<job>/<run-id>.md``. Each file is written to a temporary file in the same
directory and moved into place, so it is complete or absent (research R7, R8). A period's
lock is ``fcntl.flock`` on ``<data>/runs/<job>/<period>.lock``; the kernel releases it when
its holder ends, so a crashed run leaves no stale lock. ``fcntl`` is POSIX: macOS and Linux.
"""

import contextlib
import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

from pydantic import ValidationError

from opscout.core.chat import GatewayStatus
from opscout.core.daemon import DeliveryError, DeliveryKind, Receipt, RunRecord, StoreError


def _write_atomically(directory: Path, name: str, data: bytes) -> Path:
    """Write ``data`` to ``directory/name`` in one step. Raises ``OSError``."""
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=f".{name}.")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        return Path(temporary).replace(directory / name)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temporary).unlink()
        raise


class FileRunStore:
    """The ``RunStore`` port on JSON files."""

    def __init__(self, data: Path) -> None:
        self._runs = data / "runs"

    def hold(self, job: str, period: str) -> AbstractContextManager[bool]:
        """Hold the period's lock. Raises ``StoreError`` when the store cannot be written."""
        return self._hold(job, period)

    @contextlib.contextmanager
    def _hold(self, job: str, period: str) -> Iterator[bool]:
        directory = self._runs / job
        try:
            directory.mkdir(parents=True, exist_ok=True)
            lock = (directory / f"{period}.lock").open("a", encoding="utf-8")
        except OSError as error:
            raise StoreError(f"{directory}: cannot be written ({type(error).__name__})") from None
        with lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def delivered(self, run_key: str) -> RunRecord | None:
        """Return the newest record of the key whose outcome is ``delivered``."""
        job = run_key.split(":", 1)[0]
        for record in self._read(job):
            if record.run_key == run_key and record.outcome == "delivered":
                return record
        return None

    def write(self, record: RunRecord) -> None:
        """Write a record in one step. Raises ``StoreError``."""
        data = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        try:
            _write_atomically(self._runs / record.job, f"{record.run_id}.json", data)
        except OSError as error:
            raise StoreError(
                f"{self._runs / record.job}: the record cannot be written ({type(error).__name__})"
            ) from None

    def records(self, job: str | None, limit: int) -> list[RunRecord]:
        """Return the newest records, of one job or of all."""
        if job is not None:
            return self._read(job)[:limit]
        try:
            jobs = [path.name for path in self._runs.iterdir() if path.is_dir()]
        except OSError:
            return []
        every = [record for name in jobs for record in self._read(name)]
        return sorted(every, key=lambda record: record.run_id, reverse=True)[:limit]

    def get(self, job: str, run_id: str) -> RunRecord | None:
        """Return one record, or None when it is missing or unreadable."""
        if "/" in job or "/" in run_id or job.startswith(".") or run_id.startswith("."):
            return None
        try:
            return RunRecord.model_validate_json((self._runs / job / f"{run_id}.json").read_bytes())
        except (OSError, ValidationError):
            return None

    def _read(self, job: str) -> list[RunRecord]:
        """Return a job's readable records, newest first; others are skipped."""
        try:
            paths = sorted((self._runs / job).glob("*.json"), reverse=True)
        except OSError:
            return []
        found = []
        for path in paths:
            try:
                found.append(RunRecord.model_validate_json(path.read_bytes()))
            except (OSError, ValidationError):
                continue
        return sorted(found, key=lambda record: record.run_id, reverse=True)


class GatewayFiles:
    """The gateway's lock and state file under the data directory (spec 008, R6, R7)."""

    def __init__(self, data: Path) -> None:
        self._data = data

    @contextlib.contextmanager
    def hold(self) -> Iterator[bool]:
        """Hold the one-gateway lock; the value is False when another gateway has it."""
        self._data.mkdir(parents=True, exist_ok=True)
        with (self._data / "gateway.lock").open("a", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def write(self, status: GatewayStatus) -> None:
        """Write the state in one step; a failure is not the gateway's to stop for."""
        with contextlib.suppress(OSError):
            data = status.model_dump_json(indent=2).encode("utf-8") + b"\n"
            _write_atomically(self._data, "gateway.json", data)

    def read(self) -> GatewayStatus | None:
        """Return the last state, or None when there is none or it cannot be read."""
        try:
            return GatewayStatus.model_validate_json((self._data / "gateway.json").read_bytes())
        except (OSError, ValidationError):
            return None


class LocalOutbox:
    """The ``Delivery`` port on Markdown files: chat-output adds the direct message."""

    def __init__(self, data: Path) -> None:
        self._outbox = data / "outbox"

    def preflight(self) -> None:
        """Nothing to check: the outbox directory is created when it is written."""

    def text(self, job: str, run_id: str) -> str | None:
        """Return a delivered text, or None when it is missing or unreadable (spec 008)."""
        if "/" in job or "/" in run_id or job.startswith(".") or run_id.startswith("."):
            return None
        try:
            return (self._outbox / job / f"{run_id}.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> Receipt:
        """Write the text to the job's outbox and return the file. Raises ``DeliveryError``."""
        try:
            path = _write_atomically(self._outbox / job, f"{run_id}.md", text.encode("utf-8"))
        except OSError as error:
            raise DeliveryError(
                f"{self._outbox / job}: cannot be written ({type(error).__name__})"
            ) from None
        return Receipt(str(path))
