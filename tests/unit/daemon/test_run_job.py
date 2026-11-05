# SPDX-License-Identifier: Apache-2.0
"""``run_job``: once per period, one record per start (spec 007, US1, US3, US5)."""

from collections.abc import Mapping
from datetime import datetime, timedelta

import pytest

from opscout.core.config import Daemon, KeychainRef
from opscout.core.daemon import (
    CHECK,
    SUCCESS,
    CheckOutput,
    RecordError,
    RunnerFacts,
    RunProfile,
    RunRecord,
    RunResult,
    StoreError,
)
from opscout.services.daemon import Ports, Start, render_outcome, resolve_profile, run_job
from tests.unit.daemon.fakes import (
    SENTINEL,
    START,
    Clock,
    MemoryDelivery,
    MemoryRunStore,
    MemorySecretStore,
    ScriptedRunner,
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


FACTS = RunnerFacts(
    claude_code_version="2.1.318",
    model="claude-haiku-5-5",
    api_key_source="none",
    cost_usd=0.0005,
    turns=2,
    duration_ms=1250,
    tools_called=("StructuredOutput",),
    attempts=1,
)
OK = RunResult("ok", output=CheckOutput(ok=True, note="Fine."), facts=FACTS)
REF = KeychainRef(service="opscout-example")


class World:
    """The fakes of one test, and a way to start the job through them."""

    def __init__(self, *results: RunResult, secrets: bool = False) -> None:
        self.runner = ScriptedRunner(list(results) or [OK])
        self.store = MemoryRunStore()
        self.delivery = MemoryDelivery()
        self.keychain = MemorySecretStore()
        self.daemon = Daemon(secrets={"claude_token": REF} if secrets else {})

    def start(
        self, *, at: datetime = START, force: bool = False, clock: Clock | None = None
    ) -> RunRecord:
        ports = Ports(
            runner=self.runner,
            store=self.store,
            delivery=self.delivery,
            secrets=self.keychain,
            clock=clock or Clock([at]),
        )
        start = Start(
            job=CHECK,
            profile=resolve_profile(CHECK, None, self.daemon),
            secrets=dict(self.daemon.secrets.items()),
            trigger="scheduler",
            force=force,
            engine_version="0.0.0",
        )
        return run_job(start, ports)


@spec("FR-003")
@spec("FR-005")
def test_a_first_start_delivers_and_records_the_key() -> None:
    world = World()
    record = world.start()
    assert record.outcome == "delivered"
    assert (record.job, record.period, record.run_key) == (
        "check",
        "2026-11-05",
        "check:2026-11-05",
    )
    assert record.delivery == f"/example/outbox/check/{record.run_id}.md"
    assert record.runner == FACTS
    assert record.trigger == "scheduler"
    assert record.forced is False
    assert record.agreement is None
    assert world.store.saved == [record]
    assert [kind for _, _, kind, _ in world.delivery.sent] == ["result"]
    assert record.run_id.startswith("20261105T083000Z-")


@spec("FR-003")
def test_a_second_start_in_the_period_is_skipped_without_the_model() -> None:
    world = World()
    first = world.start()
    second = world.start(at=START + timedelta(hours=3))
    assert second.outcome == "skipped"
    assert second.reason == f"already delivered by run {first.run_id}"
    assert len(world.runner.calls) == 1
    assert len(world.delivery.sent) == 1
    assert second.runner is None


@spec("FR-004")
def test_a_start_that_cannot_take_the_lock_is_skipped() -> None:
    world = World()
    world.store.busy.add(("check", "2026-11-05"))
    record = world.start()
    assert record.outcome == "skipped"
    assert record.reason == "another start holds this period"
    assert world.runner.calls == []
    assert world.store.saved == [record]


@spec("FR-003")
@pytest.mark.parametrize(
    "result",
    [
        RunResult("error", reason="error_max_budget_usd: Reached maximum budget", facts=FACTS),
        RunResult("invalid_output", reason="note: Field required", facts=FACTS),
    ],
)
def test_a_period_that_did_not_deliver_runs_again(result: RunResult) -> None:
    world = World(result, OK)
    assert world.start().outcome in ("failed", "inconclusive")
    assert world.start(at=START + timedelta(minutes=5)).outcome == "delivered"


@spec("FR-003")
def test_force_delivers_again_and_says_so() -> None:
    world = World()
    world.start()
    record = world.start(force=True)
    assert record.outcome == "delivered"
    assert record.forced is True
    assert len(world.delivery.sent) == 2


@spec("FR-003")
def test_a_late_start_runs_for_the_current_period() -> None:
    world = World()
    world.start()
    record = world.start(at=START + timedelta(days=2))
    assert (record.outcome, record.period) == ("delivered", "2026-11-07")


@spec("FR-003")
def test_a_start_that_crosses_midnight_keeps_its_period() -> None:
    world = World()
    late = START.replace(hour=23, minute=59, second=59)
    record = world.start(clock=Clock([late, late + timedelta(seconds=5)]))
    assert record.period == "2026-11-05"
    assert record.ended_at.date().isoformat() == "2026-11-06"


@spec("FR-003")
def test_the_clock_moved_back_still_finds_the_key() -> None:
    world = World()
    world.start()
    record = world.start(at=START - timedelta(hours=2))
    assert record.outcome == "skipped"


@spec("FR-005")
def test_a_failed_delivery_is_failed_never_delivered() -> None:
    world = World()
    world.delivery.broken = True
    record = world.start()
    assert record.outcome == "failed"
    assert record.reason is not None
    assert "delivery failed" in record.reason
    assert record.delivery is None
    assert world.store.delivered("check:2026-11-05") is None


@spec("FR-006")
@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        (OK, "delivered"),
        (RunResult("refused", differences=("tools: x",), facts=FACTS), "refused"),
        (RunResult("invalid_output", reason="ok: bad", facts=FACTS), "inconclusive"),
        (RunResult("error", reason="exit 1"), "failed"),
    ],
)
def test_every_start_ends_with_one_record_and_one_outcome(result: RunResult, outcome: str) -> None:
    world = World(result)
    record = world.start()
    assert record.outcome == outcome
    assert world.store.saved == [record]
    assert (record.outcome in SUCCESS) is (outcome == "delivered")
    assert record.ended_at >= record.started_at


@spec("FR-016")
def test_refused_and_inconclusive_deliver_a_notice() -> None:
    refused = World(RunResult("refused", differences=("tools: a", "model: b"), facts=FACTS))
    record = refused.start()
    assert record.outcome == "refused"
    assert record.reason == "tools: a; model: b"
    assert [kind for _, _, kind, _ in refused.delivery.sent] == ["notice"]
    assert "refused" in refused.delivery.sent[0][3]
    assert record.delivery is not None

    inconclusive = World(RunResult("invalid_output", reason="note: Field required", facts=FACTS))
    record = inconclusive.start()
    assert record.outcome == "inconclusive"
    assert record.reason == "the output failed its schema twice: note: Field required"
    assert [kind for _, _, kind, _ in inconclusive.delivery.sent] == ["notice"]
    assert inconclusive.store.delivered("check:2026-11-05") is None


@spec("FR-016")
def test_an_error_is_failed_and_delivers_nothing() -> None:
    world = World(RunResult("error", reason="error_max_budget_usd: Reached maximum budget"))
    record = world.start()
    assert record.outcome == "failed"
    assert record.reason == "error_max_budget_usd: Reached maximum budget"
    assert world.delivery.sent == []


@spec("FR-019")
@spec("FR-023")
def test_a_configured_token_reaches_only_the_runner() -> None:
    world = World(secrets=True)
    world.keychain.values[("opscout-example", "opscout")] = SENTINEL
    record = world.start()
    assert record.outcome == "delivered"
    assert world.runner.calls[0][2] == {"CLAUDE_CODE_OAUTH_TOKEN": SENTINEL}
    assert SENTINEL not in record.model_dump_json()
    assert all(SENTINEL not in text for *_, text in world.delivery.sent)


@spec("FR-023")
@pytest.mark.parametrize("unavailable", [False, True])
def test_a_missing_secret_fails_before_the_model(unavailable: bool) -> None:
    world = World(secrets=True)
    world.keychain.unavailable = unavailable
    record = world.start()
    assert record.outcome == "failed"
    assert world.runner.calls == []
    assert record.reason is not None
    if unavailable:
        assert "keychain is unavailable" in record.reason
    else:
        assert "opscout secret set claude_token" in record.reason


@spec("FR-006")
def test_the_outcome_line() -> None:
    world = World()
    record = world.start()
    assert render_outcome(record) == f"check 2026-11-05: delivered to {record.delivery}"
    skipped = world.start()
    assert render_outcome(skipped) == (
        f"check 2026-11-05: skipped (already delivered by run {record.run_id})"
    )
    failed = World(RunResult("error", reason="exit 1")).start()
    assert render_outcome(failed) == "check 2026-11-05: failed (exit 1)"


@spec("FR-016")
def test_a_notice_that_cannot_be_delivered_is_named_in_the_reason() -> None:
    world = World(RunResult("refused", differences=("tools: a",), facts=FACTS))
    world.delivery.broken = True
    record = world.start()
    assert record.outcome == "refused"
    assert record.reason == (
        "tools: a (the notice could not be delivered: the outbox cannot be written "
        "(PermissionError))"
    )
    assert record.delivery is None


@spec("FR-006")
def test_a_runner_that_raises_still_ends_in_one_failed_record() -> None:
    class Exploding(ScriptedRunner):
        def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    world = World()
    world.runner = Exploding([])
    record = world.start()
    assert record.outcome == "failed"
    assert record.reason == "the runner failed (UnicodeDecodeError)"
    assert world.store.saved == [record]


@spec("FR-020")
def test_a_record_that_cannot_be_written_after_the_run_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()

    def broken(record: RunRecord) -> None:
        raise StoreError("/example/runs/check: the record cannot be written (OSError)")

    monkeypatch.setattr(world.store, "write", broken)
    with pytest.raises(RecordError) as error:
        world.start()
    assert str(error.value).startswith("check 2026-11-05: delivered to /example/outbox/check/")
    assert str(error.value).endswith(
        ", but its record could not be written: /example/runs/check: the record cannot be "
        "written (OSError); the next start may deliver again"
    )
