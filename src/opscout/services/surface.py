# SPDX-License-Identifier: Apache-2.0
"""Prove that the tool surface can only read (spec 011, FR-006; research R3).

The proof reuses spec 010's catalog and evaluator: a declared action passes only when it is
in AWS's recorded catalog, is not a write, and is allowed by the reference read-only
identity, whose guardrail denies secret values, credentials, reads that return plaintext
secrets, application data and sessions. So no tool can write or read a secret, even when
the identity behind it could.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from opscout.core.identity import Records, proves_allowed
from opscout.core.tools import ToolSpec
from opscout.services.identity import readonly_identity


@dataclass(frozen=True)
class SurfaceFinding:
    """One declared action that is not a proved read."""

    tool: str
    action: str
    reason: str


def prove_surface(tools: Iterable[ToolSpec], records: Records) -> list[SurfaceFinding]:
    """Return every declared action that is not a proved read; empty when the surface holds."""
    identity = readonly_identity(records.reference, records)
    findings: list[SurfaceFinding] = []
    for tool in tools:
        for action in sorted(tool.actions):
            reason: str | None = None
            if "*" in action or "?" in action:
                reason = "a wildcard; tools declare exact actions"
            elif records.catalog.name(action) is None:
                reason = "not in the catalog"
            elif records.catalog.is_write(action.lower()):
                reason = "a write"
            else:
                allowed, why = proves_allowed(identity, action, "*")
                if not allowed:
                    reason = f"not allowed by the reference read-only identity ({why})"
            if reason is not None:
                findings.append(SurfaceFinding(tool.name, action, reason))
    return findings
