# SPDX-License-Identifier: Apache-2.0
"""Clicks and reasons: what the gateway stores and shows (spec 008, US2, US3)."""

import logging
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from opscout.adapters.run_files import FileRunStore, GatewayFiles, LocalOutbox
from opscout.core.chat import MAX_REASON, Choice, GatewayStatus, Ignored, MessageRef, Reason
from opscout.core.daemon import Agreement, RunRecord
from opscout.services.chat import Clicks, GatewayRecorder, handle_event
from tests.unit.chat.fakes import (
    CHANNEL,
    REASON_SENTINEL,
    TOKEN_SENTINEL,
    USER,
    FakeChat,
    FakeTime,
)
from tests.unit.daemon.fakes import START, MemoryRunStore

RUN = "20261105T094500Z-a1b2c3"
REF = MessageRef(CHANNEL, "1762336800.000100")
TEXT = "# opscout check, 2026-11-05\n\nAll good.\n"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


def record(run_id: str = RUN) -> RunRecord:
    return RunRecord.model_validate(
        {
            "run_id": run_id,
            "job": "check",
            "period": "2026-11-05",
            "run_key": "check:2026-11-05",
            "trigger": "scheduler",
            "forced": False,
            "engine_version": "0.0.0",
            "outcome": "delivered",
            "reason": None,
            "started_at": START,
            "ended_at": START + timedelta(seconds=2),
            "delivery": f"/example/outbox/check/{run_id}.md",
            "chat": REF,
        }
    )


class World:
    def __init__(self, *, saved: bool = True, text: str | None = TEXT) -> None:
        self.store = MemoryRunStore([record()] if saved else [])
        self.chat = FakeChat()
        self.time = FakeTime()
        self.writes = 0
        original = self.store.write

        def counted(written: RunRecord) -> None:
            self.writes += 1
            original(written)

        self.store.write = counted  # type: ignore[method-assign,assignment]
        self.clicks = Clicks(
            user=USER,
            store=self.store,
            chat=self.chat,
            read_text=lambda job, run_id: text,
            clock=self.time.clock,
            sleep=self.time.sleep,
        )

    def agreement(self) -> Agreement | None:
        stored = self.store.get("check", RUN)
        return stored.agreement if stored else None


def choice(kind: str = "agree", user: str = USER) -> Choice:
    return Choice(user, "check", RUN, kind, REF, "1111.2222.example")  # type: ignore[arg-type]


def reason(text: str | None, user: str = USER) -> Reason:
    return Reason(user, "check", RUN, text, REF)


@spec("FR-015")
def test_agree_is_stored_and_shown() -> None:
    world = World()
    assert handle_event(choice("agree"), world.clicks) == "handled"
    assert world.agreement() == Agreement(choice="agree", at=world.time.now, reason=None)
    [(ref, message)] = world.chat.updates
    assert ref == REF
    assert message.context == "Agreed on 2026-11-05 09:45"
    assert message.buttons == f"check/{RUN}"
    assert message.markdown == TEXT


@spec("FR-016")
def test_disagree_opens_the_dialog_first_then_stores() -> None:
    world = World()
    assert handle_event(choice("disagree"), world.clicks) == "handled"
    assert world.chat.calls[0] == "open_reason"
    assert world.chat.dialogs == [("1111.2222.example", "check", RUN, REF)]
    stored = world.agreement()
    assert stored is not None
    assert (stored.choice, stored.reason) == ("disagree", None)
    assert world.chat.updates[-1][1].context == "Disagreed on 2026-11-05 09:45"


@spec("FR-016")
def test_a_reason_is_trimmed_and_stored_and_an_empty_one_is_none() -> None:
    world = World()
    handle_event(reason("  The note named the wrong day.  "), world.clicks)
    stored = world.agreement()
    assert stored is not None
    assert (stored.choice, stored.reason) == ("disagree", "The note named the wrong day.")
    assert world.chat.updates[-1][1].context == (
        "Disagreed on 2026-11-05 09:45: The note named the wrong day."
    )
    handle_event(reason("   "), world.clicks)
    stored = world.agreement()
    assert stored is not None
    assert stored.reason is None


@spec("FR-016")
def test_a_reason_over_500_characters_is_not_stored() -> None:
    world = World()
    assert handle_event(reason("x" * (MAX_REASON + 1)), world.clicks) == "ignored"
    assert world.agreement() is None


@spec("FR-015")
def test_the_other_choice_replaces_the_first_and_a_repeat_writes_nothing() -> None:
    world = World()
    handle_event(choice("agree"), world.clicks)
    world.time.now += timedelta(minutes=3)
    handle_event(choice("disagree"), world.clicks)
    stored = world.agreement()
    assert stored is not None
    assert stored.choice == "disagree"
    writes = world.writes
    handle_event(choice("disagree"), world.clicks)
    assert world.writes == writes
    stored_again = world.agreement()
    assert stored_again == stored


@spec("FR-015")
def test_a_record_written_moments_after_the_click_is_found() -> None:
    world = World(saved=False)

    def late(seconds: float) -> None:
        FakeTime.sleep(world.time, seconds)
        if world.time.slept and sum(world.time.slept) >= 1 and not world.store.saved:
            world.store.saved.append(record())

    world.clicks = replace(world.clicks, sleep=late)
    assert handle_event(choice("agree"), world.clicks) == "handled"
    assert world.agreement() is not None


@spec("FR-017")
def test_a_missing_record_stores_nothing_and_says_so() -> None:
    world = World(saved=False)
    assert handle_event(choice("agree"), world.clicks) == "missing"
    assert world.store.saved == []
    assert sum(world.time.slept) <= 5
    assert world.chat.updates[-1][1].context == (
        f"This choice could not be recorded (run {RUN} not found)."
    )


@spec("FR-015")
def test_without_the_outbox_text_the_record_is_still_updated() -> None:
    world = World(text=None)
    assert handle_event(choice("agree"), world.clicks) == "handled"
    assert world.agreement() is not None
    assert world.chat.updates == []


@spec("FR-015")
def test_a_failed_message_update_does_not_undo_the_record() -> None:
    world = World()
    world.chat.refuse = "message_not_found"
    assert handle_event(choice("agree"), world.clicks) == "handled"
    assert world.agreement() is not None


# Only the user (US3)


@spec("FR-014")
@pytest.mark.parametrize(
    "event",
    [
        choice("agree", user="UEXAMPLE02"),
        choice("disagree", user="UEXAMPLE02"),
        reason("x", user="UEXAMPLE02"),
        Ignored("events_api"),
        Ignored("block_actions"),
    ],
)
def test_others_and_foreign_events_change_nothing_and_get_no_answer(
    event: Choice | Reason | Ignored,
) -> None:
    world = World()
    assert handle_event(event, world.clicks) == "ignored"
    assert world.writes == 0
    assert world.chat.calls == []


@spec("FR-016")
def test_a_reason_is_kept_in_the_record_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    world = World()
    handle_event(reason(REASON_SENTINEL), world.clicks)
    stored = world.agreement()
    assert stored is not None
    assert stored.reason == REASON_SENTINEL
    assert all(REASON_SENTINEL not in r.getMessage() for r in caplog.records)


@spec("FR-019")
def test_through_the_real_files_a_reason_lands_in_its_record_only(tmp_path: Path) -> None:
    """Writes real records, outbox and gateway state, for the SC-004 scan to search."""
    store = FileRunStore(tmp_path / "data")
    outbox = LocalOutbox(tmp_path / "data")
    files = GatewayFiles(tmp_path / "data")
    time = FakeTime()
    lines: list[str] = []
    recorder = GatewayRecorder(files.write, lines.append, time.clock)
    receipt = outbox.deliver("check", RUN, "result", TEXT)
    store.write(record().model_copy(update={"delivery": receipt.location}))
    clicks = Clicks(
        user=USER, store=store, chat=FakeChat(), read_text=outbox.text,
        clock=time.clock, sleep=time.sleep,
    )  # fmt: skip
    recorder.state("connected", None)
    recorder.count(handle_event(reason(REASON_SENTINEL), clicks))
    time.now += timedelta(seconds=61)
    recorder.state("connected", None)
    stored = store.get("check", RUN)
    assert stored is not None
    assert stored.agreement is not None
    assert stored.agreement.reason == REASON_SENTINEL
    status = files.read()
    assert status is not None
    assert status.handled == 1
    assert all(REASON_SENTINEL not in line and TOKEN_SENTINEL not in line for line in lines)


@spec("FR-019")
def test_the_recorder_logs_changes_and_writes_a_heartbeat() -> None:
    time = FakeTime()
    lines: list[str] = []
    written: list[object] = []
    recorder = GatewayRecorder(written.append, lines.append, time.clock)
    recorder.state("connecting", None)
    recorder.state("connected", None)
    recorder.state("connected", None)  # within the heartbeat: nothing written
    time.now += timedelta(seconds=61)
    recorder.state("connected", None)
    recorder.state("connecting", "disconnected")
    recorder.state("stopped", "token rejected (invalid_auth)")
    assert lines == [
        "connecting to Slack",
        "connected",
        "disconnected; reconnecting",
        "stopped: token rejected (invalid_auth)",
    ]
    assert len(written) == 5


@spec("FR-015")
def test_disagree_again_keeps_the_reason() -> None:
    world = World()
    handle_event(choice("disagree"), world.clicks)
    handle_event(reason("The numbers were wrong."), world.clicks)
    writes = world.writes
    handle_event(choice("disagree"), world.clicks)  # a double click, or a second look
    stored = world.agreement()
    assert stored is not None
    assert stored.reason == "The numbers were wrong."
    assert world.writes == writes
    assert world.chat.updates[-1][1].context == (
        "Disagreed on 2026-11-05 09:45: The numbers were wrong."
    )


@spec("FR-015")
def test_clicks_on_one_run_are_handled_one_at_a_time() -> None:
    import threading

    world = World()
    inside: list[int] = []
    overlaps: list[int] = []
    original = world.store.get

    def slow_get(job: str, run_id: str) -> RunRecord | None:
        inside.append(1)
        if len(inside) > 1:
            overlaps.append(len(inside))
        threading.Event().wait(0.05)
        found = original(job, run_id)
        inside.pop()
        return found

    world.store.get = slow_get  # type: ignore[method-assign]
    threads = [
        threading.Thread(target=handle_event, args=(choice(kind), world.clicks))
        for kind in ("agree", "disagree", "agree")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlaps == []


@spec("FR-008")
def test_a_shortened_message_still_names_its_outbox_file_after_a_click() -> None:
    world = World(text="y" * 99 + "\n" + ("x" * 99 + "\n") * 200)
    handle_event(choice("agree"), world.clicks)
    message = world.chat.updates[-1][1]
    assert message.markdown.endswith(
        f"_Shortened; the full text is in /example/outbox/check/{RUN}.md._"
    )


@spec("FR-019")
def test_since_changes_with_the_state_only() -> None:
    time = FakeTime()
    written: list[GatewayStatus] = []
    recorder = GatewayRecorder(written.append, lambda line: None, time.clock)
    recorder.state("connected", None)
    time.now += timedelta(minutes=1)
    recorder.state("connecting", "disconnected")
    lost = time.now
    time.now += timedelta(minutes=1)
    recorder.state("connecting", "cannot connect (URLError)")
    assert written[-1].since == lost
    assert recorder.current == "connecting"
