# SPDX-License-Identifier: Apache-2.0
"""The triage tools: begin, check, agreement, evidence and infrastructure code (spec 012).

None of them calls AWS, so the surface check covers them as they are (research R15). They
write only the run's local record (research R8) and read only the evidence store and the
configured infrastructure clones (research R6).
"""

from collections.abc import Mapping
from typing import Any

from opscout.core.aws import find_environment
from opscout.core.tools import ErrorReason, ToolError
from opscout.services import iac, triage
from opscout.services.tools.runtime import Call, Outcome

MAX_IDS = 20


def _stores(call: Call) -> triage.Stores:
    if call.evidence is None or call.records is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "the triage stores are not available")
    return triage.Stores(call.evidence, call.records, call.engine_version)


def _required(call: Call, name: str) -> str:
    value = call.argument(name)
    if not isinstance(value, str) or not value:
        raise ToolError(ErrorReason.INVALID_INPUT, f"{name} is required")
    return value


def _optional(call: Call, name: str) -> str | None:
    return None if call.argument(name) is None else _required(call, name)


def begin_triage(call: Call) -> Outcome:
    """Open a run for an alert (FR-003, FR-008)."""
    text = _required(call, "text")
    data = triage.begin(text, _optional(call, "alert_time"), call.config, call.now, _stores(call))
    name = data["resolution"]["environment"]
    environment = None
    if name is not None and call.config is not None and call.config.aws is not None:
        environment = find_environment(call.config.aws, name)
    return Outcome(data=data, environment=environment)


def check_verdict(call: Call) -> Outcome:
    """Check a verdict for a run (FR-018, FR-019)."""
    run_id = _required(call, "run_id")
    verdict = call.argument("verdict")
    if not isinstance(verdict, Mapping):
        raise ToolError(ErrorReason.INVALID_INPUT, "verdict must be an object")
    return Outcome(data=triage.check_verdict(run_id, verdict, call.now, _stores(call)))


def record_agreement(call: Call) -> Outcome:
    """Store the user's answer (FR-024)."""
    run_id = _required(call, "run_id")
    answer = _required(call, "answer")
    reason = _optional(call, "reason")
    return Outcome(data=triage.record_agreement(run_id, answer, reason, call.now, _stores(call)))


def show_evidence(call: Call) -> Outcome:
    """Return stored results by identifier, for the skeptic (research R13)."""
    ids = call.argument("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS:
        raise ToolError(ErrorReason.INVALID_INPUT, f"give 1 to {MAX_IDS} evidence ids")
    if call.evidence is None:
        raise ToolError(ErrorReason.NOT_CONFIGURED, "the evidence store is not available")
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for evidence_id in ids:
        stored = call.evidence.get(str(evidence_id))
        if stored is None:
            missing.append(str(evidence_id))
        else:
            items.append(
                {
                    "id": stored.id,
                    "tool": stored.tool,
                    "stored_at": stored.stored_at,
                    "result": stored.result,
                }
            )
    return Outcome(data={"items": items, "missing": missing})


def search_iac(call: Call) -> Outcome:
    """Search the configured infrastructure clones (research R6)."""
    pattern = _required(call, "pattern")
    return Outcome(
        data=iac.search(
            call.config,
            call.files,
            pattern,
            environment=_optional(call, "environment"),
            clone=_optional(call, "clone"),
        )
    )


def read_iac(call: Call) -> Outcome:
    """Read lines of one file in a configured clone (research R6)."""
    path = _required(call, "path")
    start, end = call.argument("start"), call.argument("end")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ToolError(ErrorReason.INVALID_INPUT, "start and end are line numbers")
    return Outcome(data=iac.read(call.config, call.files, path, start, end))
