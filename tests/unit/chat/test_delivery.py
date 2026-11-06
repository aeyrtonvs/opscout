# SPDX-License-Identifier: Apache-2.0
"""ChatDelivery: the outbox, then one direct message, retried for 10 minutes (spec 008)."""

import pytest

from opscout.core.chat import MessageRef
from opscout.core.daemon import DeliveryError, SecretError, SecretStatus
from opscout.services.chat import ChatDelivery
from tests.unit.chat.fakes import CHANNEL, USER, FakeChat, FakeTime
from tests.unit.daemon.fakes import MemoryDelivery

RUN = "20261105T094500Z-a1b2c3"
TEXT = "# opscout check, 2026-11-05\n\nAll good.\n"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


class World:
    def __init__(self, chat: FakeChat | None = None) -> None:
        self.outbox = MemoryDelivery()
        self.chat = chat or FakeChat()
        self.time = FakeTime()
        self.checked = 0
        self.delivery = ChatDelivery(
            outbox=self.outbox,
            chat=self.chat,
            user=USER,
            check=self.check,
            clock=self.time.clock,
            sleep=self.time.sleep,
        )

    def check(self) -> None:
        self.checked += 1


@spec("FR-006")
def test_the_outbox_first_then_one_direct_message() -> None:
    world = World()
    receipt = world.delivery.deliver("check", RUN, "result", TEXT)
    assert receipt.location == f"/example/outbox/check/{RUN}.md"
    assert receipt.chat == MessageRef(CHANNEL, "1762336800.000001")
    assert [kind for _, _, kind, _ in world.outbox.sent] == ["result"]
    [(user, message)] = world.chat.sent
    assert user == USER
    assert message.markdown == TEXT
    assert message.buttons == f"check/{RUN}"


@spec("FR-007")
def test_an_unreachable_service_is_retried_with_growing_waits() -> None:
    world = World(FakeChat(unavailable=2))
    receipt = world.delivery.deliver("check", RUN, "result", TEXT)
    assert receipt.chat is not None
    assert world.time.slept == [5, 10]


@spec("FR-007")
def test_the_service_s_wait_is_honored() -> None:
    world = World(FakeChat(unavailable=1, retry_after=30))
    world.delivery.deliver("check", RUN, "result", TEXT)
    assert world.time.slept == [30]


@spec("FR-007")
def test_after_10_minutes_the_delivery_fails_and_the_outbox_copy_stays() -> None:
    world = World(FakeChat(unavailable=1000))
    with pytest.raises(DeliveryError, match="could not be reached for 10 minutes"):
        world.delivery.deliver("check", RUN, "result", TEXT)
    assert sum(world.time.slept) <= 600
    assert world.time.slept[:6] == [5, 10, 20, 40, 60, 60]
    assert len(world.outbox.sent) == 1
    assert world.chat.sent == []


@spec("FR-007")
def test_a_refusal_is_not_retried() -> None:
    world = World(FakeChat(refuse="invalid_auth"))
    with pytest.raises(DeliveryError, match=r"Slack refused the message \(invalid_auth\)"):
        world.delivery.deliver("check", RUN, "result", TEXT)
    assert world.time.slept == []
    assert world.chat.calls == ["send"]


@spec("FR-010")
def test_the_recipient_is_always_the_configured_user() -> None:
    world = World()
    for text in ("<@UEXAMPLE02> please read", "#alerts-example\n<!channel>"):
        world.delivery.deliver("check", RUN, "result", text)
    assert {user for user, _ in world.chat.sent} == {USER}


@spec("FR-006")
def test_preflight_checks_the_token_before_the_model() -> None:
    world = World()
    world.delivery.preflight()
    assert world.checked == 1

    def missing() -> None:
        raise SecretError("slack_bot_token", SecretStatus("missing"))

    unready = ChatDelivery(
        outbox=MemoryDelivery(), chat=FakeChat(), user=USER, check=missing,
        clock=FakeTime().clock, sleep=FakeTime().sleep,
    )  # fmt: skip
    with pytest.raises(DeliveryError, match="opscout secret set slack_bot_token"):
        unready.preflight()


@spec("FR-009")
def test_a_notice_has_no_buttons() -> None:
    world = World()
    world.delivery.deliver("check", RUN, "notice", TEXT)
    assert world.chat.sent[0][1].buttons is None


@spec("FR-024")
def test_a_failure_notice_that_cannot_be_sent_is_dropped() -> None:
    world = World(FakeChat(refuse="invalid_auth"))
    assert world.delivery.alert("check", RUN, "# failed") is None
    sent = World()
    ref = sent.delivery.alert("check", RUN, "# opscout check, 2026-11-05: failed")
    assert ref is not None
    assert sent.chat.sent[0][1].buttons is None
