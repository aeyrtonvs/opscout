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

from opscout.core.daemon import DeliveryError, DeliveryKind, RunRecord, StoreError


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


class LocalOutbox:
    """The ``Delivery`` port on Markdown files: chat-output adds the direct message."""

    def __init__(self, data: Path) -> None:
        self._outbox = data / "outbox"

    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> str:
        """Write the text to the job's outbox and return the file. Raises ``DeliveryError``."""
        try:
            path = _write_atomically(self._outbox / job, f"{run_id}.md", text.encode("utf-8"))
        except OSError as error:
            raise DeliveryError(
                f"{self._outbox / job}: cannot be written ({type(error).__name__})"
            ) from None
        return str(path)
