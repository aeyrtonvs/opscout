# SPDX-License-Identifier: Apache-2.0
"""The daemon core: jobs, run profiles, run records and the ports (spec 007, ADR-0021).

Nothing here does I/O. A job is engine-defined; the configuration only schedules it and
overrides its limits. The ports are what ``services`` needs from the host: a model runner,
a run store, a delivery, a secret store and a scheduler. Each has a fake in the tests and
an adapter in ``opscout.adapters``, built only by ``opscout.entrypoints.daemon``.
"""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from opscout.core.config import KeychainRef

Outcome = Literal["delivered", "skipped", "refused", "inconclusive", "failed"]
Trigger = Literal["scheduler", "user"]
DeliveryKind = Literal["result", "notice"]

SUCCESS: Final[frozenset[str]] = frozenset({"delivered", "skipped"})
"""The outcomes that exit 0 (FR-006)."""

LABEL_PREFIX: Final = "opscout."
"""The prefix of every job opscout installs; nothing else is read or changed (FR-009)."""

MINIMUM_CLAUDE_CODE: Final = (2, 1, 318)
"""The Claude Code version whose flags and reports the runner was checked against."""

TOKEN_VARIABLE: Final = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105  (a variable name)
"""Where the fallback token goes, in the child's environment only (FR-019)."""


@dataclass(frozen=True)
class RunProfile:
    """Everything a model run may use, passed to Claude Code explicitly (FR-014)."""

    tools: tuple[str, ...]
    mcp_servers: Mapping[str, Mapping[str, Any]]
    model: str
    budget_usd: float
    max_turns: int
    output: type[BaseModel]
    secrets: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Environment variable → secret name."""

    @property
    def schema(self) -> dict[str, Any]:
        """Return the JSON Schema of the output."""
        return self.output.model_json_schema()


@dataclass(frozen=True)
class StartupReport:
    """What Claude Code says it started with: the ``system/init`` event (FR-015)."""

    tools: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    model: str
    permission_mode: str
    plugins: tuple[tuple[str, str], ...]
    """Each loaded plugin's name and path; built-in plugins have the path ``builtin``."""
    api_key_source: str
    claude_code_version: str


class RunnerFacts(BaseModel):
    """The run's own reports, kept in the record (FR-018)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claude_code_version: str | None
    model: str | None
    api_key_source: str | None
    cost_usd: float
    turns: int
    duration_ms: int
    tools_called: tuple[str, ...]
    attempts: int


@dataclass(frozen=True)
class RunResult:
    """What a runner returns: an output, or why there is none."""

    status: Literal["ok", "refused", "invalid_output", "error"]
    output: BaseModel | None = None
    differences: tuple[str, ...] = ()
    reason: str | None = None
    facts: RunnerFacts | None = None


class RunRecord(BaseModel):
    """One start of a job, written once as JSON (FR-021). Never a secret or the prompt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    record_version: Literal[1] = 1
    job: str
    period: str
    run_key: str
    trigger: Trigger
    forced: bool
    engine_version: str
    outcome: Outcome
    reason: str | None
    started_at: datetime
    ended_at: datetime
    inputs: tuple[str, ...] = ()
    delivery: str | None = None
    runner: RunnerFacts | None = None
    agreement: None = None


class CheckOutput(BaseModel):
    """The ``check`` job's output: the model says it is there."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    ok: bool = Field(description="Always true.")
    note: str = Field(min_length=1, max_length=300, description="One short sentence.")


@dataclass(frozen=True)
class Job:
    """An engine-defined procedure; the configuration schedules it (FR-007)."""

    name: str
    description: str
    profile: RunProfile
    prompt: str
    render: Callable[[Any, RunnerFacts, str], str]
    """The delivered text, from the validated output, the facts and the period."""


def _render_check(output: CheckOutput, facts: RunnerFacts, period: str) -> str:
    return "\n".join(
        [
            f"# opscout check, {period}",
            "",
            "The scheduled path works: Claude Code ran with no tools, its start-up report "
            "matched the profile, and its output passed the schema.",
            "",
            f"- Model's note: {output.note}",
            f"- Claude Code: {facts.claude_code_version}",
            f"- Model: {facts.model}",
            f"- Login source (apiKeySource): {facts.api_key_source}",
            f"- Cost: {facts.cost_usd:.4f} USD, {facts.turns} turn(s), {facts.attempts} attempt(s)",
            f"- Duration: {facts.duration_ms / 1000:.1f} s",
            "",
        ]
    )


CHECK: Final = Job(
    name="check",
    description="Runs the whole scheduled path once with no tools, as a diagnostic.",
    profile=RunProfile(
        tools=(),
        mcp_servers=MappingProxyType({}),
        model="haiku",
        budget_usd=0.05,
        max_turns=3,
        output=CheckOutput,
    ),
    prompt=(
        "This is opscout's scheduled self-check. Reply only through the structured output: "
        "set ok to true and note to one short sentence saying you received this message."
    ),
    render=_render_check,
)

JOBS: Final[Mapping[str, Job]] = MappingProxyType({CHECK.name: CHECK})


@dataclass(frozen=True)
class SecretStatus:
    """Whether a secret is in the keychain; never its value (FR-023)."""

    state: Literal["present", "missing", "unavailable"]
    reason: str | None = None


class SecretError(Exception):
    """A secret cannot be resolved; the message names it, never its value."""

    def __init__(self, name: str, status: SecretStatus) -> None:
        if status.state == "missing":
            message = (
                f"the secret {name} is missing from the keychain; store it with "
                f"opscout secret set {name}"
            )
        else:
            message = f"the keychain is unavailable for the secret {name} ({status.reason})"
        super().__init__(message)
        self.name = name
        self.status = status


class StoreError(Exception):
    """The run store cannot be used; a job does not run without it (FR-004)."""


class RecordError(StoreError):
    """A run ended but its record could not be written; the next start may run again."""


class DeliveryError(Exception):
    """A delivery failed; the outcome is ``failed``, never ``delivered`` (FR-005)."""


class SchedulerError(Exception):
    """The scheduler cannot list or change the installed jobs."""


@dataclass(frozen=True)
class ScheduledJob:
    """A job as the scheduler should run it (FR-010), whatever the scheduler."""

    name: str
    arguments: tuple[str, ...]
    """The absolute program, then its arguments."""
    times: tuple[tuple[int, int, int], ...]
    """Each (ISO weekday 1 to 7, hour, minute), in the machine's local time."""
    log: Path
    environment: Mapping[str, str]

    @property
    def label(self) -> str:
        """Return the scheduler's name for the job."""
        return f"{LABEL_PREFIX}{self.name}"


@dataclass(frozen=True)
class InstalledJob:
    """A job opscout installed, as the scheduler has it."""

    label: str
    path: Path
    content: bytes
    loaded: bool
    arguments: tuple[str, ...]
    modified_at: datetime | None

    @property
    def name(self) -> str:
        """Return the job's name, without the label prefix."""
        return self.label.removeprefix(LABEL_PREFIX)


@dataclass(frozen=True)
class SchedulerChange:
    """One change to the installed jobs."""

    action: Literal["add", "update", "remove", "load"]
    label: str
    current: bytes | None
    new: bytes | None
    job: ScheduledJob | None = None


@dataclass(frozen=True)
class PendingSchedule:
    """The changes that would make the installed jobs match the wanted ones."""

    changes: tuple[SchedulerChange, ...]


class Runner(Protocol):
    """Starts one restricted, checked model run (FR-014 to FR-018)."""

    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
        """Run the model; ``env`` holds the resolved secrets for the child only."""
        ...


class RunStore(Protocol):
    """Keeps one record per start, and the lock on a period (FR-004, FR-020)."""

    def hold(self, job: str, period: str) -> AbstractContextManager[bool]:
        """Hold the period's lock; the context's value is False when another start has it."""
        ...

    def delivered(self, run_key: str) -> RunRecord | None:
        """Return the newest record of the key whose outcome is ``delivered``."""
        ...

    def write(self, record: RunRecord) -> None:
        """Write a record in one step."""
        ...

    def records(self, job: str | None, limit: int) -> list[RunRecord]:
        """Return the newest records, of one job or of all."""
        ...


class Delivery(Protocol):
    """The output port (FR-005, FR-008)."""

    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> str:
        """Deliver the text and return where it went. Raises ``DeliveryError``."""
        ...


class SecretStore(Protocol):
    """The OS keychain (FR-023)."""

    def status(self, name: str, ref: KeychainRef) -> SecretStatus:
        """Return whether the secret is there, without returning it."""
        ...

    def resolve(self, name: str, ref: KeychainRef) -> str:
        """Return the value. Raises ``SecretError``."""
        ...

    def store(self, name: str, ref: KeychainRef, value: str) -> None:
        """Store the value. Raises ``SecretError``."""
        ...


class Scheduler(Protocol):
    """The OS scheduler (FR-009 to FR-013)."""

    def installed(self) -> list[InstalledJob]:
        """Return every job under the label prefix, with whether it is loaded."""
        ...

    def installed_times(self) -> dict[str, datetime]:
        """Return each installed job's name and install time, without asking the service."""
        ...

    def plan(self, wanted: Sequence[ScheduledJob]) -> PendingSchedule:
        """Return the changes that make the installed jobs exactly the wanted ones."""
        ...

    def apply(self, pending: PendingSchedule) -> None:
        """Apply the changes. Raises ``SchedulerError``."""
        ...
