# SPDX-License-Identifier: Apache-2.0
"""Alert triage's run: begin, check the verdict, record the agreement (spec 012).

A run opens with ``begin``, which parses and resolves the alert in code, sets the windows
and returns the settings and the ticket format (FR-003, FR-008, FR-022). ``check_verdict``
validates and checks the verdict against the evidence stored in the run, allows one retry,
then closes the run as inconclusive (FR-018, FR-019; research R9). ``record_agreement``
stores the user's answer (FR-024). Records hold the alert's digest, never its text (FR-025).
"""

import hashlib
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from pydantic import ValidationError

from opscout.core import alerts
from opscout.core.config import Configuration, InfrastructureClone, Triage
from opscout.core.tools import ErrorReason, ToolError
from opscout.core.triage import (
    Agreement,
    AlertRef,
    CheckedCitation,
    CheckSummary,
    EvidenceStore,
    RunSettings,
    TriageRecord,
    TriageStore,
    UncheckedCitation,
    Verdict,
    check,
)
from opscout.services.redact import OPTIONAL_KINDS, redact
from opscout.services.writeups import resolve_formats

EVIDENCE_HOURS: Final = 24
HISTORY_PERIOD: Final = 3600
BEFORE_ALERT: Final = timedelta(hours=1)
AFTER_ALERT: Final = timedelta(minutes=30)
CHANGES_BEFORE: Final = timedelta(hours=24)
_SCOPE_FIELDS: Final = ("account", "environment", "project")
_MARKER = re.compile(r"\[[a-z]+(?:-[a-z]+)*\]")
_CONFIG_FIX: Final = "add an aws section to the configuration (docs/reference/tools.md)"


@dataclass(frozen=True)
class Stores:
    """What a run reads and writes: the evidence, the records, the engine's version."""

    evidence: EvidenceStore
    records: TriageStore
    engine_version: str


def find_secrets(text: str) -> tuple[str, ...]:
    """The kinds of secret-shaped values in ``text``; redaction markers are not secrets.

    Redacting a marker again yields a marker, so the text holds a secret only when
    redaction changes it beyond its markers.
    """
    redacted, _ = redact(text, keep=OPTIONAL_KINDS)
    if _MARKER.sub("[x]", redacted) == _MARKER.sub("[x]", text):
        return ()
    _, counts = redact(_MARKER.sub(",", text), keep=OPTIONAL_KINDS)
    return tuple(sorted(counts)) or ("secret",)


def _run_id(now: datetime) -> str:
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def _alert_time(fields: Mapping[str, str], named: str | None, now: datetime) -> dict[str, Any]:
    """The alert's time: from the alert, else the user, else now (FR-008)."""
    found: dict[str, Any] = {}
    raw = fields.get("time")
    if raw is not None:
        try:
            parsed = datetime.fromisoformat(raw.replace(" UTC", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return {"time": parsed, "source": "alert", "offset": parsed.strftime("%:z")}
        found["unparsed"] = "the alert's time could not be read"
    if named is not None:
        try:
            given = datetime.fromisoformat(named)
        except ValueError:
            raise ToolError(ErrorReason.INVALID_INPUT, "alert_time is not ISO 8601") from None
        if given.tzinfo is None:
            raise ToolError(ErrorReason.INVALID_INPUT, "alert_time needs an offset")
        return {"time": given, "source": "user", **found}
    return {"time": now, "source": "invocation", **found}


def _resolution(
    config: Configuration | None, fields: Mapping[str, str], text: str
) -> dict[str, Any]:
    if config is None or config.aws is None:
        return {"status": "aws-not-configured", "environment": None, "fix": _CONFIG_FIX}
    scope = {name: value for name, value in fields.items() if name in _SCOPE_FIELDS}
    resolution = alerts.resolve(config.aws, scope, text)
    if resolution.environment is not None and resolution.matched_by is not None:
        field, value = resolution.matched_by
        return {
            "status": "resolved",
            "environment": resolution.environment.name,
            "matched_by": {"field": field, "value": value},
        }
    if scope:
        return {
            "status": "out-of-scope",
            "environment": None,
            "unmatched": [{"field": name, "value": value} for name, value in scope.items()],
        }
    return {"status": "unknown", "environment": None}


def _clones(triage: Triage, environment: str | None) -> list[str]:
    def serves(clone: InfrastructureClone) -> bool:
        return clone.environments is None or environment in clone.environments

    return [clone.name for clone in triage.infrastructure if serves(clone)]


def _ticket_format(config: Configuration | None) -> dict[str, Any]:
    writeups = config.writeups if config is not None else Configuration(schema_version=1).writeups
    ticket = next(f for f in resolve_formats(writeups) if f.name == "ticket")
    return {
        "name": ticket.name,
        "origin": ticket.origin,
        "description": ticket.format.description,
        "sections": list(ticket.format.sections),
        "max_lines": ticket.format.max_lines,
        "rules": [*ticket.shared_rules, *ticket.format.rules],
        "language": writeups.language,
    }


def begin(
    text: str, alert_time: str | None, config: Configuration | None, now: datetime, stores: Stores
) -> dict[str, Any]:
    """Open a run: parse, resolve, set the windows and settings, write the open record."""
    stores.evidence.prune(now - timedelta(hours=EVIDENCE_HOURS))
    if config is not None and config.alerts is not None:
        parsed = alerts.parse_alert(text, config.alerts)
        alert: dict[str, Any] = parsed.render()
        fields = {name: field.value for name, field in parsed.fields.items()}
    else:
        alert = {"matched": False, "reason": "no alert format is configured"}
        fields = {}
    resolution = _resolution(config, fields, text)
    when = _alert_time(fields, alert_time, now)
    anchor: datetime = min(when["time"], now)
    if when["time"] > now:
        when["future"] = "the alert's time is after now, so the windows end now"
    triage = (config.triage if config is not None else None) or Triage()
    history = timedelta(days=triage.metric_history_days)
    run_id = _run_id(now)
    record = TriageRecord(
        run_id=run_id,
        skill_version=stores.engine_version,
        engine_version=stores.engine_version,
        started_at=now,
        alert=AlertRef(
            format=alert.get("format"),
            environment=resolution["environment"],
            resource=fields.get("resource"),
            digest=hashlib.sha256(text.encode()).hexdigest(),
        ),
        settings=RunSettings(skeptic=triage.skeptic, observability=triage.observability),
    )
    stores.records.write(record)
    return {
        "run_id": run_id,
        "started_at": now,
        "alert": alert,
        "resolution": resolution,
        "cloud_reads": resolution["status"] == "resolved",
        "alert_time": when,
        "windows": {
            "alert": {"since": anchor - BEFORE_ALERT, "until": min(anchor + AFTER_ALERT, now)},
            "changes": {"since": anchor - CHANGES_BEFORE, "until": min(anchor + AFTER_ALERT, now)},
            "history": {"since": min(anchor, now) - history, "until": min(anchor, now)},
        },
        "settings": {
            "metric_history_days": triage.metric_history_days,
            "history_period": HISTORY_PERIOD,
            "skeptic": triage.skeptic,
            "observability": triage.observability,
            "infrastructure": _clones(triage, resolution["environment"]),
        },
        "ticket_format": _ticket_format(config),
    }


def _validation_failures(error: ValidationError) -> list[dict[str, str]]:
    """The validator's messages, never the refused values."""
    return [
        {
            "where": ".".join(str(part) for part in detail["loc"]) or "verdict",
            "reason": f"invalid: {detail['msg']}",
        }
        for detail in error.errors(include_input=False, include_url=False)
    ]


_HINTS: Final = {
    "quote not found": (
        'copy one value exactly as the result shows it, or a "key": value fragment of it'
    ),
    "unknown evidence": "cite only evidence ids that this run's tool results carried",
    "evidence from another run": "cite only evidence read in this run",
    "no checked support for the classification": (
        "give a claim that cites opscout evidence, or classify as inconclusive"
    ),
    "no checked support for the cause": "cite opscout evidence for the cause, or set it to null",
    "no checked support for the threshold assessment": (
        "cite the alarm or metric evidence the assessment rests on, or use not-assessable"
    ),
}


def _hint(reason: str) -> dict[str, str]:
    hint = _HINTS.get(reason)
    return {"hint": hint} if hint else {}


def _observability_tools(verdict: Verdict) -> list[str]:
    cites = [*verdict.threshold.cites, *(c for claim in verdict.claims for c in claim.cites)]
    if verdict.cause is not None:
        cites += verdict.cause.cites
    return sorted({c.observability for c in cites if isinstance(c, UncheckedCitation)})


def _tool_counts(stores: Stores, record: TriageRecord, now: datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in stores.evidence.since(record.started_at):
        if item.stored_at <= now:
            counts[item.tool] = counts.get(item.tool, 0) + 1
    return dict(sorted(counts.items()))


def _next_start(stores: Stores, record: TriageRecord) -> datetime | None:
    """When the next run on this machine began: evidence after it is not this run's."""
    later = [
        other.started_at
        for other in stores.records.records(NEIGHBOURS)
        if isinstance(other, TriageRecord) and other.started_at > record.started_at
    ]
    return min(later, default=None)


NEIGHBOURS: Final = 50


def check_verdict(
    run_id: str, verdict_json: Mapping[str, Any], now: datetime, stores: Stores
) -> dict[str, Any]:
    """Check one verdict for the run, applying research R9's attempts."""
    record = stores.records.get(run_id)
    if record is None:
        raise ToolError(ErrorReason.INVALID_INPUT, "no triage run has that id")
    revising = record.outcome == "checked" and record.settings.skeptic and not record.revision_tried
    if record.outcome != "open" and not revising:
        raise ToolError(ErrorReason.INVALID_INPUT, "the run is closed")
    try:
        verdict: Verdict | None = Verdict.model_validate(verdict_json)
    except ValidationError as error:
        verdict, failures = None, _validation_failures(error)
    if verdict is not None:
        result = check(
            verdict,
            stores.evidence.get,
            record.started_at,
            find_secrets,
            until=_next_start(stores, record),
            run_environment=record.alert.environment,
        )
        failures = [
            {"where": f.where, "reason": f.reason, **_hint(f.reason)} for f in result.failures
        ]
    passed = verdict is not None and not failures
    attempts = record.check.attempts + 1
    closing = {
        "ended_at": now,
        "duration_seconds": (now - record.started_at).total_seconds(),
        "tools": _tool_counts(stores, record, now),
    }
    if revising:
        update: dict[str, Any] = {"revision_tried": True, "revised": passed}
        if passed and verdict is not None:
            update |= {"verdict": verdict, "observability_tools": _observability_tools(verdict)}
        else:
            update["check"] = CheckSummary(attempts=record.check.attempts, failures=failures)
        record = record.model_copy(update=update | closing)
        outcome, retry = "checked", False
    elif passed and verdict is not None:
        record = record.model_copy(
            update={
                "outcome": "checked",
                "verdict": verdict,
                "observability_tools": _observability_tools(verdict),
                "check": CheckSummary(attempts=attempts),
            }
            | closing
        )
        outcome, retry = "checked", False
    elif attempts < 2:
        record = record.model_copy(
            update={"check": CheckSummary(attempts=attempts, failures=failures)}
        )
        outcome, retry = "open", True
    else:
        record = record.model_copy(
            update={
                "outcome": "inconclusive",
                "check": CheckSummary(attempts=attempts, failures=failures),
            }
            | closing
        )
        outcome, retry = "inconclusive", False
    stores.records.write(record)
    return {
        "run_id": run_id,
        "passed": passed,
        "failures": failures,
        "retry": retry,
        "final": outcome != "open",
        "outcome": outcome,
        "verdict": record.verdict.model_dump(mode="json") if record.verdict else None,
    }


MAX_REASON: Final = 500


def record_agreement(
    run_id: str, answer: str, reason: str | None, now: datetime, stores: Stores
) -> dict[str, Any]:
    """Store the user's answer for a closed run (FR-024); a second answer replaces it."""
    record = stores.records.get(run_id)
    if record is None:
        raise ToolError(ErrorReason.INVALID_INPUT, "no triage run has that id")
    if record.outcome == "open":
        raise ToolError(ErrorReason.INVALID_INPUT, "the run has no checked verdict yet")
    if answer not in ("agree", "disagree", "not-answered"):
        raise ToolError(ErrorReason.INVALID_INPUT, "answer is agree, disagree or not-answered")
    if reason is not None and len(reason) > MAX_REASON:
        raise ToolError(ErrorReason.INVALID_INPUT, f"reason is at most {MAX_REASON} characters")
    cleaned = redact(reason, keep=OPTIONAL_KINDS)[0] if reason else None
    agreement = Agreement.model_validate({"answer": answer, "reason": cleaned, "at": now})
    stores.records.write(record.model_copy(update={"agreement": agreement}))
    return {"run_id": run_id, "agreement": agreement.model_dump(mode="json")}


def summarize(records: Sequence[TriageRecord], now: datetime) -> list[dict[str, Any]]:
    """One line's facts per run, with ``abandoned`` for an open run past 24 hours."""
    rows = []
    for record in records:
        outcome: str = record.outcome
        if outcome == "open" and now - record.started_at > timedelta(hours=EVIDENCE_HOURS):
            outcome = "abandoned"
        rows.append(
            {
                "run_id": record.run_id,
                "started_at": record.started_at,
                "format": record.alert.format,
                "environment": record.alert.environment,
                "outcome": outcome,
                "classification": record.verdict.classification if record.verdict else None,
                "agreement": record.agreement.answer if record.agreement else None,
            }
        )
    return rows


__all__ = [
    "CheckedCitation",
    "Stores",
    "begin",
    "check_verdict",
    "find_secrets",
    "record_agreement",
    "summarize",
]
