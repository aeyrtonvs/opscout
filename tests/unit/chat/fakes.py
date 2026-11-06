# SPDX-License-Identifier: Apache-2.0
"""Fakes for chat output: a chat service, a clock and a sleep (spec 008)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from opscout.core.chat import (
    ChatMessage,
    ChatRefusedError,
    ChatUnavailableError,
    MessageRef,
)

ZONE = timezone(timedelta(hours=1))
USER = "UEXAMPLE01"
CHANNEL = "DEXAMPLE01"
TOKEN_SENTINEL = "xoxb-sentinel-chat-token-0123456789"  # noqa: S105  (a fake)
REASON_SENTINEL = "sentinel reason text 0123456789"


@dataclass
class FakeChat:
    """Records sends, updates and dialogs; fails the next ``unavailable`` calls, or refuses."""

    sent: list[tuple[str, ChatMessage]] = field(default_factory=list)
    updates: list[tuple[MessageRef, ChatMessage]] = field(default_factory=list)
    dialogs: list[tuple[str, str, str, MessageRef]] = field(default_factory=list)
    unavailable: int = 0
    retry_after: float | None = None
    refuse: str | None = None
    calls: list[str] = field(default_factory=list)

    def _fail(self) -> None:
        if self.refuse is not None:
            raise ChatRefusedError(self.refuse)
        if self.unavailable > 0:
            self.unavailable -= 1
            raise ChatUnavailableError("Slack could not be reached", self.retry_after)

    def send(self, user: str, message: ChatMessage) -> MessageRef:
        self.calls.append("send")
        self._fail()
        self.sent.append((user, message))
        return MessageRef(CHANNEL, f"1762336800.{len(self.sent):06d}")

    def update(self, ref: MessageRef, message: ChatMessage) -> None:
        self.calls.append("update")
        self._fail()
        self.updates.append((ref, message))

    def open_reason(self, trigger: str, job: str, run_id: str, ref: MessageRef) -> None:
        self.calls.append("open_reason")
        self._fail()
        self.dialogs.append((trigger, job, run_id, ref))


@dataclass
class FakeTime:
    """A clock and a sleep that share one fake time."""

    now: datetime = field(default_factory=lambda: datetime(2026, 11, 5, 9, 45, tzinfo=ZONE))
    slept: list[float] = field(default_factory=list)

    def clock(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)
