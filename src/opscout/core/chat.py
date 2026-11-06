# SPDX-License-Identifier: Apache-2.0
"""Chat output: the neutral message, the gateway's events and the ports (spec 008).

Nothing here knows Slack. ``services.chat`` renders messages, retries deliveries and
handles clicks through these types; ``adapters.slack`` maps them to and from Slack.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

AgreementChoice = Literal["agree", "disagree"]

MAX_REASON: Final = 500
"""The longest reason a user may give for disagreeing (FR-016)."""


@dataclass(frozen=True)
class MessageRef:
    """Where a delivered message is: its direct-message channel and timestamp."""

    channel: str
    ts: str


@dataclass(frozen=True)
class ChatMessage:
    """A message to the user, in neutral form (research R3)."""

    markdown: str
    notification: str
    buttons: str | None = None
    """``<job>/<run-id>`` for a result's agreement buttons; None for a notice."""
    context: str | None = None
    """The last line: the run, then the user's choice."""


@dataclass(frozen=True)
class Choice:
    """A click on Agree or Disagree."""

    user: str
    job: str
    run_id: str
    choice: AgreementChoice
    ref: MessageRef
    trigger: str


@dataclass(frozen=True)
class Reason:
    """A submitted reason dialog."""

    user: str
    job: str
    run_id: str
    reason: str | None
    ref: MessageRef


@dataclass(frozen=True)
class Ignored:
    """Anything else the chat service sent; only counted."""

    kind: str


GatewayEvent = Choice | Reason | Ignored
GatewayState = Literal["connecting", "connected", "stopped"]


class GatewayStatus(BaseModel):
    """What the gateway last said about itself, for status and the session start (R7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GatewayState
    since: datetime
    last_seen: datetime
    reason: str | None = None
    """A kind of trouble, such as ``token rejected``; never a token or a message."""
    handled: int = 0
    ignored: int = 0


class ChatUnavailableError(Exception):
    """The chat service could not take the request now; it may later (FR-007)."""

    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


class ChatRefusedError(Exception):
    """The chat service refused the request for good, such as a rejected token."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Slack refused the message ({code})")
        self.code = code


class Chat(Protocol):
    """Sends and changes the user's direct messages (FR-006 to FR-010)."""

    def send(self, user: str, message: ChatMessage) -> MessageRef:
        """Send a direct message. Raises ``ChatUnavailableError`` or ``ChatRefusedError``."""
        ...

    def update(self, ref: MessageRef, message: ChatMessage) -> None:
        """Replace a sent message. Raises ``ChatUnavailableError`` or ``ChatRefusedError``."""
        ...

    def open_reason(self, trigger: str, job: str, run_id: str, ref: MessageRef) -> None:
        """Open the reason dialog for a disagreement. Raises like ``send``."""
        ...


class Gateway(Protocol):
    """Holds the outward connection and hands each event to a handler (FR-012)."""

    def serve(
        self,
        handle: Callable[[GatewayEvent], None],
        state: Callable[[GatewayState, str | None], None],
    ) -> int:
        """Serve until stopped; return 0 when it must not be restarted, else 1."""
        ...

    def stop(self) -> None:
        """Ask ``serve`` to return."""
        ...
