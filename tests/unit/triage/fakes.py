# SPDX-License-Identifier: Apache-2.0
"""In-memory stores for alert triage's ports (spec 012)."""

import secrets
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from opscout.core.triage import StoredEvidence, TriageRecord, Unreadable


@dataclass
class MemoryEvidence:
    """Keeps evidence in a dict; ``fail`` makes every put raise OSError."""

    items: dict[str, StoredEvidence] = field(default_factory=dict)
    fail: bool = False

    def put(self, tool: str, result: Mapping[str, Any], at: datetime) -> str:
        if self.fail:
            raise OSError("read-only file system")
        evidence_id = f"ev-{secrets.token_hex(5)}"
        self.items[evidence_id] = StoredEvidence(evidence_id, tool, at, dict(result))
        return evidence_id

    def get(self, evidence_id: str) -> StoredEvidence | None:
        return self.items.get(evidence_id)

    def since(self, at: datetime) -> list[StoredEvidence]:
        return [item for item in self.items.values() if item.stored_at >= at]

    def prune(self, older_than: datetime) -> None:
        self.items = {k: v for k, v in self.items.items() if v.stored_at >= older_than}


@dataclass
class MemoryRecords:
    """Keeps triage records in a dict, newest last."""

    items: dict[str, TriageRecord] = field(default_factory=dict)

    def write(self, record: TriageRecord) -> None:
        self.items[record.run_id] = record

    def get(self, run_id: str) -> TriageRecord | None:
        return self.items.get(run_id)

    def records(self, limit: int) -> list[TriageRecord | Unreadable]:
        newest = sorted(self.items.values(), key=lambda r: r.started_at, reverse=True)
        return list(newest[:limit])


@dataclass
class MemoryFiles:
    """A FileReader over a dict of roots to {relative path: text or bytes}."""

    roots: dict[str, dict[str, str | bytes]] = field(default_factory=dict)
    links: dict[str, dict[str, str]] = field(default_factory=dict)
    """root -> {relative link: target}, the target relative to the root or absolute."""

    def exists(self, root: str) -> bool:
        return root in self.roots

    def files(self, root: str) -> Iterator[str]:
        yield from sorted(self.roots.get(root, {}))

    def resolve(self, root: str, relative: str) -> str | None:
        target = self.links.get(root, {}).get(relative, relative)
        if target.startswith("/") or ".." in target.split("/"):
            return None
        return target

    def read_text(self, root: str, relative: str) -> str | None:
        content = self.roots.get(root, {}).get(relative)
        return content if isinstance(content, str) else None
