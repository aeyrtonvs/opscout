# SPDX-License-Identifier: Apache-2.0
"""The evidence store, as files under the data directory (spec 012, research R2).

Each tool result the model saw, already redacted and capped, is kept at
``<data>/triage/evidence/<id>.json`` for the citation check. Files older than 24 hours are
pruned by the server. A file that cannot be read is skipped, never raised.
"""

import contextlib
import json
import os
import secrets
import tempfile
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from opscout.core.triage import EVIDENCE_ID, StoredEvidence


class FileEvidence:
    """Implements ``EvidenceStore`` on one JSON file per result."""

    def __init__(self, data: Path) -> None:
        self._directory = data / "triage" / "evidence"

    def put(self, tool: str, result: Mapping[str, Any], at: datetime) -> str:
        """Store the result; raises ``OSError`` when it cannot be written."""
        self._directory.mkdir(parents=True, exist_ok=True)
        evidence_id = f"ev-{secrets.token_hex(5)}"
        document = {"id": evidence_id, "tool": tool, "stored_at": at.isoformat(), "result": result}
        handle, temporary = tempfile.mkstemp(dir=self._directory, prefix=f".{evidence_id}.")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(document, file, ensure_ascii=False, default=str)
            Path(temporary).replace(self._directory / f"{evidence_id}.json")
        except BaseException:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
            raise
        return evidence_id

    def get(self, evidence_id: str) -> StoredEvidence | None:
        """The stored result, or None when absent, unreadable or not an identifier."""
        if not EVIDENCE_ID.fullmatch(evidence_id):
            return None
        return self._read(self._directory / f"{evidence_id}.json")

    def since(self, at: datetime) -> list[StoredEvidence]:
        """Everything stored at or after ``at``, oldest first."""
        found = [item for item in self._all() if item.stored_at >= at]
        return sorted(found, key=lambda item: item.stored_at)

    def prune(self, older_than: datetime) -> None:
        """Delete what was stored before ``older_than``, and files that cannot be read."""
        for path in self._files():
            item = self._read(path)
            if item is None or item.stored_at < older_than:
                with contextlib.suppress(OSError):
                    path.unlink()

    def _files(self) -> Iterator[Path]:
        if not self._directory.is_dir():
            return
        yield from self._directory.glob("ev-*.json")

    def _all(self) -> Iterator[StoredEvidence]:
        for path in self._files():
            item = self._read(path)
            if item is not None:
                yield item

    @staticmethod
    def _read(path: Path) -> StoredEvidence | None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            return StoredEvidence(
                id=document["id"],
                tool=document["tool"],
                stored_at=datetime.fromisoformat(document["stored_at"]),
                result=document["result"],
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
