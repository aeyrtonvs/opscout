# SPDX-License-Identifier: Apache-2.0
"""Chat output: render a message, deliver it with retries, handle clicks (spec 008).

Everything here works through ``opscout.core.chat`` and ``opscout.core.daemon``; the Slack
adapter only maps between Slack and these neutral types.
"""

import contextlib
import itertools
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from opscout.core.chat import (
    MAX_REASON,
    Chat,
    ChatMessage,
    ChatRefusedError,
    ChatUnavailableError,
    Choice,
    GatewayEvent,
    GatewayState,
    GatewayStatus,
    Ignored,
    MessageRef,
    Reason,
)
from opscout.core.daemon import (
    Agreement,
    Delivery,
    DeliveryError,
    Receipt,
    RunRecord,
    RunStore,
    SecretError,
)

LIMIT: Final = 11_000
"""The most characters of a message's text; Slack's markdown limit is 12,000 (research R3)."""

NOTIFICATION: Final = 150
PATIENCE: Final = 600.0
"""How long one delivery keeps trying, in seconds (FR-007)."""

MessageKind = Literal["result", "notice", "failure"]

_MARKS = re.compile(r"[*_`~>#]+|\[([^\]]*)\]\([^)]*\)")


def render_message(
    text: str,
    *,
    job: str,
    run_id: str,
    kind: MessageKind,
    outbox: str,
    context: str | None = None,
) -> ChatMessage:
    """Return the direct message for a job's text (research R3)."""
    markdown = text
    if len(text) > LIMIT:
        note = f"\n\n_Shortened; the full text is in {outbox}._"
        cut = text.rfind("\n", 0, LIMIT - len(note))
        markdown = text[: cut if cut > 0 else LIMIT - len(note)].rstrip("\n") + note
    first = next((line for line in text.splitlines() if line.strip()), "")
    plain = " ".join(_MARKS.sub(lambda m: m.group(1) or "", first).split())
    result = kind == "result"
    return ChatMessage(
        markdown=markdown,
        notification=plain[:NOTIFICATION],
        buttons=f"{job}/{run_id}" if result else None,
        context=(context or f"opscout {job}, run {run_id}") if result else None,
    )


def _waits() -> Iterator[float]:
    """Return the waits between tries: 5, 10, 20, 40, then 60 seconds."""
    return itertools.chain((5.0, 10.0, 20.0, 40.0), itertools.repeat(60.0))


def persist[T](
    call: Callable[[], T], clock: Callable[[], datetime], sleep: Callable[[float], None]
) -> T:
    """Call until the chat service accepts, for up to ``PATIENCE`` seconds (FR-007).

    Raises ``DeliveryError``: at once when the service refuses, else when time runs out.
    """
    began = clock()
    waits = _waits()
    while True:
        try:
            return call()
        except ChatRefusedError as error:
            raise DeliveryError(str(error)) from None
        except ChatUnavailableError as error:
            wait = error.retry_after if error.retry_after is not None else next(waits)
            if (clock() - began).total_seconds() + wait > PATIENCE:
                raise DeliveryError("Slack could not be reached for 10 minutes") from None
            sleep(wait)


class ChatDelivery:
    """The ``Delivery`` port with chat: the outbox copy, then one direct message (FR-006)."""

    def __init__(
        self,
        *,
        outbox: Delivery,
        chat: Chat,
        user: str,
        check: Callable[[], None],
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._outbox = outbox
        self._chat = chat
        self._user = user
        self._check = check
        self._clock = clock
        self._sleep = sleep

    def preflight(self) -> None:
        """Check the outbox and the chat token before any model run."""
        self._outbox.preflight()
        try:
            self._check()
        except SecretError as error:
            raise DeliveryError(str(error)) from None

    def deliver(
        self, job: str, run_id: str, kind: Literal["result", "notice"], text: str
    ) -> Receipt:
        """Write the outbox copy, then send the message; ``delivered`` needs both."""
        receipt = self._outbox.deliver(job, run_id, kind, text)
        message = render_message(text, job=job, run_id=run_id, kind=kind, outbox=receipt.location)
        try:
            ref = persist(lambda: self._chat.send(self._user, message), self._clock, self._sleep)
        except DeliveryError as error:
            raise DeliveryError(str(error), location=receipt.location) from None
        return Receipt(receipt.location, ref)

    def alert(self, job: str, run_id: str, text: str) -> MessageRef | None:
        """Send a failed run's notice (FR-024); None when it could not be sent."""
        message = render_message(text, job=job, run_id=run_id, kind="failure", outbox="")
        try:
            return persist(lambda: self._chat.send(self._user, message), self._clock, self._sleep)
        except DeliveryError:
            return None


WAIT_FOR_RECORD: Final = 5.0
"""How long a click waits for its run's record, written moments after the message."""

Outcome = Literal["handled", "missing", "ignored"]


@dataclass(frozen=True)
class Clicks:
    """What handling a click needs: the configured user, the store, the chat, the text."""

    user: str
    store: RunStore
    chat: Chat
    read_text: Callable[[str, str], str | None]
    """The delivered text of a job's run, from its outbox file; None when unreadable."""
    clock: Callable[[], datetime]
    sleep: Callable[[float], None]


def handle_event(event: GatewayEvent, clicks: Clicks) -> Outcome:
    """Store the configured user's choice or reason, and show it (FR-014 to FR-017).

    Everything else is ignored: other people's clicks, other interactions and events. A
    chat failure while showing the choice never undoes the stored one.
    """
    if isinstance(event, Ignored) or event.user != clicks.user:
        return "ignored"
    if isinstance(event, Choice) and event.choice == "disagree":
        # First: the click's trigger lasts 3 seconds, and the record may take longer.
        _quietly(lambda: clicks.chat.open_reason(event.trigger, event.job, event.run_id, event.ref))
    if isinstance(event, Reason):
        reason = event.reason.strip() if event.reason else ""
        if len(reason) > MAX_REASON:
            return "ignored"
        agreement = Agreement(choice="disagree", at=clicks.clock(), reason=reason or None)
    else:
        agreement = Agreement(choice=event.choice, at=clicks.clock())
    # One click of a run at a time: the chat client hands events to a pool of threads, and
    # two quick clicks must not both read the record before either writes it.
    with _run_lock(event.job, event.run_id):
        record = _wait_for(clicks, event.job, event.run_id)
        text = clicks.read_text(event.job, event.run_id)
        if record is None:
            context = f"This choice could not be recorded (run {event.run_id} not found)."
            _show(clicks, event, text, "", context)
            return "missing"
        stored = record.agreement
        if isinstance(event, Choice) and stored is not None and stored.choice == event.choice:
            agreement = stored  # the same button again: a reason given before stays
        if stored is None or (stored.choice, stored.reason) != (agreement.choice, agreement.reason):
            clicks.store.write(record.model_copy(update={"agreement": agreement}))
            stored = agreement
        _show(clicks, event, text, record.delivery or "", describe_agreement(stored))
    return "handled"


_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _run_lock(job: str, run_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((job, run_id), threading.Lock())


def describe_agreement(agreement: Agreement) -> str:
    """Return the message's last line after a click."""
    verb = "Agreed" if agreement.choice == "agree" else "Disagreed"
    line = f"{verb} on {agreement.at:%Y-%m-%d %H:%M}"
    return f"{line}: {agreement.reason}" if agreement.reason else line


def _wait_for(clicks: Clicks, job: str, run_id: str) -> RunRecord | None:
    began = clicks.clock()
    while True:
        record = clicks.store.get(job, run_id)
        if record is not None or (clicks.clock() - began).total_seconds() >= WAIT_FOR_RECORD:
            return record
        clicks.sleep(0.5)


def _show(
    clicks: Clicks, event: Choice | Reason, text: str | None, outbox: str, context: str
) -> None:
    if text is None:
        return
    message = render_message(
        text, job=event.job, run_id=event.run_id, kind="result", outbox=outbox, context=context
    )
    _quietly(lambda: clicks.chat.update(event.ref, message))


def _quietly(call: Callable[[], None]) -> None:
    """Make a chat call whose failure must not stop the handling (the gateway logs counts)."""
    with contextlib.suppress(ChatRefusedError, ChatUnavailableError):
        call()


HEARTBEAT: Final = 60.0
"""How often a connected gateway rewrites its state, so a stale one shows (research R7)."""

_LINES: Final = {"connecting": "connecting to Slack", "connected": "connected"}


class GatewayRecorder:
    """Keeps the gateway's state file and log: states and counts, never content (FR-019)."""

    def __init__(
        self,
        write: Callable[[GatewayStatus], None],
        log: Callable[[str], None],
        clock: Callable[[], datetime],
    ) -> None:
        self._write = write
        self._log = log
        self._clock = clock
        self._status: GatewayStatus | None = None
        self._handled = 0
        self._ignored = 0

    def state(self, state: GatewayState, reason: str | None, *, quiet: bool = False) -> None:
        """Record a state; log and write it when it changes, else every ``HEARTBEAT``.

        ``quiet`` writes without a log line, for a caller that logs its own.
        """
        now = self._clock()
        current = self._status
        changed = current is None or (current.state, current.reason) != (state, reason)
        if not changed and current is not None:
            if (now - current.last_seen).total_seconds() < HEARTBEAT:
                return
        elif not quiet:
            if state == "stopped":
                self._log(f"stopped: {reason}")
            elif state == "connecting" and reason:
                self._log(f"{reason}; reconnecting")
            else:
                self._log(_LINES[state])
        moved = current is None or current.state != state
        self._status = GatewayStatus(
            state=state,
            since=now if moved or current is None else current.since,
            last_seen=now,
            reason=reason,
            handled=self._handled,
            ignored=self._ignored,
        )
        self._write(self._status)

    @property
    def current(self) -> GatewayState | None:
        """Return the last recorded state, if any."""
        return self._status.state if self._status else None

    def count(self, outcome: Outcome) -> None:
        """Count a handled or ignored event; written with the next state."""
        if outcome == "ignored":
            self._ignored += 1
        else:
            self._handled += 1
