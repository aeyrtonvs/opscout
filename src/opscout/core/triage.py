# SPDX-License-Identifier: Apache-2.0
"""Alert triage's domain: the verdict, its check, the run record and the ports (spec 012).

The check is pure: it receives a lookup for stored evidence and a secret finder, so this
module does no I/O and imports no service (ADR-0011). Its rules are contracts/verdict.md's:
every checked citation names evidence stored in this run and quotes a value found in it;
a classification, a cause and a threshold assessment need checked support; the verdict's
environment matches its evidence; and no text holds a secret-shaped value (FR-017, FR-018,
FR-021).
"""

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

EVIDENCE_PATTERN = r"^ev-[0-9a-f]{10}$"
RUN_ID_PATTERN = r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$"
SKIPPED_DIRECTORIES = frozenset({".git", ".terraform", ".terragrunt-cache", "node_modules"})
"""Directories the infrastructure-code tools never read (research R6)."""
EVIDENCE_KINDS = ("metrics", "logs", "changes", "configuration", "observability")
SHORT_QUOTE = 4
"""A quote shorter than this must equal a whole value, or "5" would match any number."""
TOKEN_QUOTE = 8
"""A quote shorter than this must sit on token boundaries, or "202" would match any year."""


def _zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise PydanticCustomError("opscout_timezone", "unknown timezone") from None
    return name


def _unique(kinds: list[str]) -> list[str]:
    if len(set(kinds)) != len(kinds):
        raise PydanticCustomError("opscout_missing", "each kind may be listed only once")
    return kinds


_Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
_Quote = Annotated[str, StringConstraints(min_length=1, max_length=300)]
_Zone = Annotated[str, AfterValidator(_zone)]

_STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)


class CheckedCitation(BaseModel):
    """A citation of a stored tool result, checked in code."""

    model_config = _STRICT

    evidence: Annotated[str, StringConstraints(pattern=EVIDENCE_PATTERN)]
    quote: _Quote


class UncheckedCitation(BaseModel):
    """A citation of the observability server's output, which opscout cannot check."""

    model_config = _STRICT

    observability: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    quote: _Quote


Citation = CheckedCitation | UncheckedCitation


class Cause(BaseModel):
    """What caused the alert, when the evidence says."""

    model_config = _STRICT

    text: _Text
    cites: Annotated[list[Citation], Field(min_length=1, max_length=10)]


class Threshold(BaseModel):
    """Keep the threshold, tune it, or say why it cannot be assessed."""

    model_config = _STRICT

    assessment: Literal["keep", "tune", "not-assessable"]
    proposal: Annotated[str, StringConstraints(min_length=1, max_length=300)] | None = None
    reason: _Text
    cites: Annotated[list[Citation], Field(max_length=10)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _proposal_iff_tune(self) -> "Threshold":
        if (self.assessment == "tune") != (self.proposal is not None):
            raise PydanticCustomError("opscout_threshold", "a proposal is required for tune only")
        return self


class Claim(BaseModel):
    """One claim of the verdict and the evidence it rests on."""

    model_config = _STRICT

    text: _Text
    cites: Annotated[list[Citation], Field(min_length=1, max_length=10)]


class SkepticNote(BaseModel):
    """Whether the skeptic pass ran and disagreed (research R13)."""

    model_config = _STRICT

    ran: bool = False
    disagreed: bool = False
    note: _Text | None = None


class Verdict(BaseModel):
    """The structured verdict of one triage (contracts/verdict.md, FR-017)."""

    model_config = _STRICT

    classification: Literal["real", "false-positive", "inconclusive"]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    cause: Cause | None = None
    threshold: Threshold
    claims: Annotated[list[Claim], Field(max_length=20)] = Field(default_factory=list)
    assumptions: Annotated[list[_Text], Field(max_length=20)] = Field(default_factory=list)
    timezone: _Zone
    alert_timezone: _Zone | None = None
    alert_time_source: Literal["alert", "user", "invocation"]
    environment: Annotated[str, StringConstraints(max_length=64)] | None = None
    identity: Annotated[str, StringConstraints(max_length=64)] | None = None
    missing: Annotated[
        list[Literal["metrics", "logs", "changes", "configuration", "observability"]],
        AfterValidator(_unique),
    ] = Field(default_factory=list)
    skeptic: SkepticNote = Field(default_factory=SkepticNote)


@dataclass(frozen=True)
class StoredEvidence:
    """One tool result as the model saw it: redacted and capped (research R2)."""

    id: str
    tool: str
    stored_at: datetime
    result: Mapping[str, Any]
    citable: bool = True
    """False for a result that only echoes its input, and for every error (review H1)."""


@dataclass(frozen=True)
class Failure:
    """One reason the verdict did not pass, at a JSON path of the verdict."""

    where: str
    reason: str


@dataclass(frozen=True)
class CheckResult:
    """The check's outcome; it passed when nothing failed."""

    failures: tuple[Failure, ...]

    @property
    def passed(self) -> bool:
        """True when no rule failed."""
        return not self.failures


Lookup = Callable[[str], StoredEvidence | None]
SecretFinder = Callable[[str], Sequence[str]]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _scalars(value: object) -> Iterator[object]:
    """Every value in a JSON-like structure, never its keys."""
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _scalars(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _scalars(item)
    elif value is not None:
        yield value


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _number(text: str) -> float | None:
    plain = text.replace(",", "")
    if not _NUMBER.fullmatch(plain):
        return None
    number = float(plain)
    return number if math.isfinite(number) else None


_PAIR = re.compile(r'"[^"]+":(?:"[^"]|-?\d|true|false)')
"""A JSON key followed by a scalar value: a fragment must hold one, so a field name, or a
key with an empty, null or nested value, never counts as a quote (review H1)."""


def _fragment_found(quote: str, data: object) -> bool:
    """Whether the quote is a ``"key": value`` fragment of the data as the model saw it."""
    wanted = "".join(quote.split())
    if not _PAIR.search(wanted):
        return False
    shown = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return wanted in "".join(shown.split())


def _joins(left: str, right: str) -> bool:
    return bool(left and right) and (
        (left.isdigit() and right.isdigit()) or (left.isalpha() and right.isalpha())
    )


def _bounded(wanted: str, text: str) -> bool:
    """Whether ``wanted`` occurs in ``text`` without cutting a number or a word."""
    start = text.find(wanted)
    while start != -1:
        end = start + len(wanted)
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if not _joins(before, wanted[0]) and not _joins(wanted[-1], after):
            return True
        start = text.find(wanted, start + 1)
    return False


def quote_found(quote: str, result: Mapping[str, Any]) -> bool:
    """Whether the quote appears in one value of the result's data, or is a ``"key": value``
    fragment of it as the model saw it (research R5). The envelope around the data, which
    every result shares, never counts (review H1)."""
    data = result.get("data")
    wanted = _collapse(quote)
    if not wanted or data is None:
        return False
    if _fragment_found(quote, data):
        return True
    as_number = _number(wanted)
    for value in _scalars(data):
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, int | float):
            if as_number is not None and float(value) == as_number:
                return True
            text = repr(value) if isinstance(value, float) else str(value)
        else:
            text = _collapse(str(value))
            if as_number is not None and _number(text) == as_number:
                return True
        if text == wanted:
            return True
        if SHORT_QUOTE <= len(wanted) < TOKEN_QUOTE and _bounded(wanted, text):
            return True
        if len(wanted) >= TOKEN_QUOTE and wanted in text:
            return True
    return False


def _citations(verdict: Verdict) -> Iterator[tuple[str, str, Citation]]:
    """(group, path, citation) for every citation, in the verdict's order."""
    if verdict.cause is not None:
        for index, citation in enumerate(verdict.cause.cites):
            yield "cause", f"cause.cites[{index}]", citation
    for index, citation in enumerate(verdict.threshold.cites):
        yield "threshold", f"threshold.cites[{index}]", citation
    for number, claim in enumerate(verdict.claims):
        for index, citation in enumerate(claim.cites):
            yield "claims", f"claims[{number}].cites[{index}]", citation


def _texts(verdict: Verdict) -> Iterator[tuple[str, str]]:
    """(path, text) for every free text of the verdict."""
    yield "summary", verdict.summary
    if verdict.cause is not None:
        yield "cause.text", verdict.cause.text
    if verdict.threshold.proposal is not None:
        yield "threshold.proposal", verdict.threshold.proposal
    yield "threshold.reason", verdict.threshold.reason
    for number, claim in enumerate(verdict.claims):
        yield f"claims[{number}].text", claim.text
    for index, assumption in enumerate(verdict.assumptions):
        yield f"assumptions[{index}]", assumption
    if verdict.skeptic.note is not None:
        yield "skeptic.note", verdict.skeptic.note
    for _, path, citation in _citations(verdict):
        yield f"{path}.quote", citation.quote


def check(
    verdict: Verdict,
    lookup: Lookup,
    run_started: datetime,
    find_secrets: SecretFinder,
    *,
    until: datetime | None = None,
    run_environment: str | None = None,
) -> CheckResult:
    """Check every citation and rule of contracts/verdict.md (FR-018, FR-021).

    Evidence counts only when it is citable and was stored between ``run_started`` and
    ``until``, the start of the next run; the verdict's environment must be the run's.
    """
    failures: list[Failure] = []
    supported: set[str] = set()
    cited: list[StoredEvidence] = []
    for group, path, citation in _citations(verdict):
        if not isinstance(citation, CheckedCitation):
            continue
        stored = lookup(citation.evidence)
        if stored is None:
            failures.append(Failure(path, "unknown evidence"))
            continue
        if stored.stored_at < run_started or (until is not None and stored.stored_at >= until):
            failures.append(Failure(path, "evidence from another run"))
            continue
        if not stored.citable:
            failures.append(Failure(path, "evidence that cannot be cited"))
            continue
        cited.append(stored)
        if quote_found(citation.quote, stored.result):
            supported.add(group)
        else:
            failures.append(Failure(path, "quote not found"))
    if verdict.classification != "inconclusive" and "claims" not in supported:
        failures.append(Failure("classification", "no checked support for the classification"))
    if verdict.cause is not None and "cause" not in supported:
        failures.append(Failure("cause", "no checked support for the cause"))
    if verdict.threshold.assessment != "not-assessable" and "threshold" not in supported:
        failures.append(Failure("threshold", "no checked support for the threshold assessment"))
    for field in ("environment", "identity"):
        stated = {s.result.get(field) for s in cited if s.result.get(field) is not None}
        if stated and stated != {getattr(verdict, field)}:
            failures.append(Failure(field, f"{field} differs from the evidence"))
    if run_environment is not None and verdict.environment not in (None, run_environment):
        failures.append(Failure("environment", "environment differs from the run's"))
    for path, text in _texts(verdict):
        kinds = find_secrets(text)
        if kinds:
            failures.append(Failure(path, f"secret-shaped value ({', '.join(sorted(kinds))})"))
    return CheckResult(tuple(failures))


# The run record (research R8, data-model.md)

Outcome = Literal["open", "checked", "inconclusive"]


class AlertRef(BaseModel):
    """The alert by reference: never its text (FR-025)."""

    model_config = _STRICT

    format: str | None
    environment: str | None
    resource: str | None
    digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CheckSummary(BaseModel):
    """The check's attempts and the failures of the last failed one."""

    model_config = _STRICT

    attempts: Annotated[int, Field(ge=0, le=3)] = 0
    failures: list[dict[str, str]] = Field(default_factory=list)


class Agreement(BaseModel):
    """The user's answer to "do you agree?" (FR-024)."""

    model_config = _STRICT

    answer: Literal["agree", "disagree", "not-answered"]
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None
    at: AwareDatetime


class RunSettings(BaseModel):
    """The settings a run used."""

    model_config = _STRICT

    skeptic: bool = False
    observability: bool = False


class TriageRecord(BaseModel):
    """One triage's local record (FR-025). Never the alert's text or a secret's value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
    record_version: Literal[1] = 1
    skill: Literal["alert-triage"] = "alert-triage"
    skill_version: str
    """The plugin's version, which moves in lockstep with the engine's (ADR-0016)."""
    engine_version: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    outcome: Outcome = "open"
    alert: AlertRef
    settings: RunSettings = Field(default_factory=RunSettings)
    verdict: Verdict | None = None
    check: CheckSummary = Field(default_factory=CheckSummary)
    revised: bool = False
    revision_tried: bool = False
    tools: dict[str, int] = Field(default_factory=dict)
    observability_tools: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
    cost_usd: float | None = None
    agreement: Agreement | None = None


@dataclass(frozen=True)
class Unreadable:
    """A record file that could not be read; listed by name, never raised."""

    name: str


# Ports


class EvidenceStore(Protocol):
    """Where tool results are kept for the check (research R2)."""

    def put(
        self, tool: str, result: Mapping[str, Any], at: datetime, *, citable: bool = True
    ) -> str:
        """Store one result; return its new evidence identifier."""
        ...

    def get(self, evidence_id: str) -> StoredEvidence | None:
        """The stored result, or None."""
        ...

    def since(self, at: datetime) -> list[StoredEvidence]:
        """Everything stored at or after ``at``."""
        ...

    def prune(self, older_than: datetime) -> None:
        """Delete everything stored before ``older_than``."""
        ...


class TriageStore(Protocol):
    """Where triage records live (research R8)."""

    def write(self, record: TriageRecord) -> None:
        """Write the record, replacing an earlier version of it."""
        ...

    def get(self, run_id: str) -> TriageRecord | None:
        """The record, or None."""
        ...

    def records(self, limit: int) -> list[TriageRecord | Unreadable]:
        """The newest records first."""
        ...


class FileReader(Protocol):
    """Reads files under a root, for the infrastructure-code tools (research R6)."""

    def exists(self, root: str) -> bool:
        """Whether the root is an existing directory."""
        ...

    def files(self, root: str) -> Iterator[str]:
        """Relative paths of the regular files under the root, symbolic links resolved inside it."""
        ...

    def resolve(self, root: str, relative: str) -> str | None:
        """The relative path once resolved, or None when it leaves the root."""
        ...

    def read_text(self, root: str, relative: str) -> str | None:
        """The file's text, or None when it is binary or unreadable."""
        ...


EVIDENCE_ID = re.compile(EVIDENCE_PATTERN)
