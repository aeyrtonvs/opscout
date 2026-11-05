# SPDX-License-Identifier: Apache-2.0
"""Confirmation codes for changes a person approves (specs 006 and 007).

A code is the first 12 hexadecimal characters of a SHA-256 over the change, so it names
exactly one change: once the current state or the wanted state differs, the code does too.
"""

import hashlib

from opscout.core.daemon import PendingSchedule


def confirmation_code(current: bytes | None, new: bytes) -> str:
    """Return the code that confirms changing ``current`` into ``new``."""
    digest = hashlib.sha256()
    digest.update(b"absent" if current is None else b"present:" + current)
    digest.update(b"\x00new:")
    digest.update(new)
    return digest.hexdigest()[:12]


def schedule_code(pending: PendingSchedule) -> str:
    """Return the code that confirms a change to the scheduled jobs (spec 007, FR-029)."""
    digest = hashlib.sha256()
    for change in pending.changes:
        for part in (change.action, change.label):
            digest.update(part.encode("utf-8") + b"\x00")
        for content in (change.current, change.new):
            digest.update(b"absent\x00" if content is None else b"present:%d:" % len(content))
            digest.update(content or b"")
    return digest.hexdigest()[:12]
