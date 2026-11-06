# SPDX-License-Identifier: Apache-2.0
"""The Slack adapter: direct messages, the reason dialog and the Socket Mode gateway.

It maps between Slack and the neutral types of ``opscout.core.chat`` and nothing more
(spec 008, research R2 to R6). The ``slack_sdk`` loggers are disabled: at debug level they
print payloads, and a Socket Mode URL carries a short-lived ticket (research R1).
"""

import logging
import re
import ssl
import threading
import urllib.error
from collections.abc import Callable, Mapping
from typing import Any, Final

import truststore
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.builtin import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from opscout.core.chat import (
    MAX_REASON,
    ChatMessage,
    ChatRefusedError,
    ChatUnavailableError,
    Choice,
    GatewayEvent,
    GatewayState,
    Ignored,
    MessageRef,
    Reason,
)

_LIBRARY = logging.getLogger("slack_sdk")
# Above CRITICAL, so neither it nor any child logger makes a record at all; no handler and
# no propagation, so nothing could print one anyway.
_LIBRARY.setLevel(logging.CRITICAL + 1)
_LIBRARY.addHandler(logging.NullHandler())  # keeps logging's last-resort handler quiet too
_LIBRARY.propagate = False

TRANSIENT: Final = frozenset(
    {"ratelimited", "internal_error", "fatal_error", "service_unavailable", "request_timeout"}
)
"""Error codes worth another try (research R4); any other code is a refusal."""

AGREE: Final = "opscout_agree"
DISAGREE: Final = "opscout_disagree"
REASON_VIEW: Final = "opscout_reason"
_RUN = re.compile(r"^([a-z][a-z0-9-]{0,39})/(\d{8}T\d{6}Z-[0-9a-f]{6})$")


def blocks_of(message: ChatMessage) -> list[dict[str, Any]]:
    """Return the message's blocks (research R3)."""
    blocks: list[dict[str, Any]] = [{"type": "markdown", "text": message.markdown}]
    if message.buttons is not None:
        blocks.append(
            {
                "type": "actions",
                "block_id": "opscout_actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": action,
                        "text": {"type": "plain_text", "text": label},
                        "value": message.buttons,
                    }
                    for action, label in ((AGREE, "Agree"), (DISAGREE, "Disagree"))
                ],
            }
        )
    if message.context is not None:
        # Plain text, so a reason the user typed is shown as written, never as markup.
        blocks.append(
            {
                "type": "context",
                "block_id": "opscout_context",
                "elements": [{"type": "plain_text", "text": message.context}],
            }
        )
    return blocks


def _tls() -> ssl.SSLContext:
    """Return a TLS context that trusts what the operating system trusts.

    Some Pythons, such as python.org's on macOS, ship without a certificate store, so the
    default context cannot verify Slack; ``truststore`` asks the system instead, which also
    covers a company's own certificate authority (research R1).
    """
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _web_client(token: str) -> WebClient:
    return WebClient(token=token, logger=_LIBRARY, ssl=_tls())


class SlackChat:
    """The ``Chat`` port on Slack's Web API."""

    def __init__(
        self,
        token: Callable[[], str],
        client: Callable[[str], WebClient] = _web_client,
    ) -> None:
        self._token = token
        self._make = client
        self._client: WebClient | None = None
        self._channels: dict[str, str] = {}

    def _web(self) -> WebClient:
        if self._client is None:
            self._client = self._make(self._token())
        return self._client

    def send(self, user: str, message: ChatMessage) -> MessageRef:
        """Open the direct message with the user, once, and post to it."""
        if user not in self._channels:
            self._channels[user] = _call(
                lambda: str(self._web().conversations_open(users=user)["channel"]["id"])
            )

        def post() -> MessageRef:
            posted = self._web().chat_postMessage(
                channel=self._channels[user],
                text=message.notification,
                blocks=blocks_of(message),
            )
            return MessageRef(str(posted["channel"]), str(posted["ts"]))

        result: MessageRef = _call(post)
        return result

    def update(self, ref: MessageRef, message: ChatMessage) -> None:
        """Replace a sent message with the whole new one."""
        _call(
            lambda: self._web().chat_update(
                channel=ref.channel,
                ts=ref.ts,
                text=message.notification,
                blocks=blocks_of(message),
            )
        )

    def open_reason(self, trigger: str, job: str, run_id: str, ref: MessageRef) -> None:
        """Open the optional reason dialog of a disagreement (FR-016)."""
        view = {
            "type": "modal",
            "callback_id": REASON_VIEW,
            "private_metadata": f"{job}/{run_id} {ref.channel} {ref.ts}",
            "title": {"type": "plain_text", "text": "Disagree"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Skip"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": REASON_VIEW,
                    "optional": True,
                    "label": {"type": "plain_text", "text": "What was wrong? (optional)"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "reason",
                        "multiline": True,
                        "max_length": MAX_REASON,
                    },
                }
            ],
        }
        _call(lambda: self._web().views_open(trigger_id=trigger, view=view))


def _call(request: Callable[[], Any]) -> Any:
    """Make a Web API call; map its failures to ``ChatUnavailableError`` or ``ChatRefusedError``."""
    try:
        return request()
    except SlackApiError as error:
        code = str(error.response.get("error") or "unknown_error")
        status = error.response.status_code
        if code in TRANSIENT or status >= 500:
            after = error.response.headers.get("Retry-After") if error.response.headers else None
            raise ChatUnavailableError(code, float(after) if after else None) from None
        raise ChatRefusedError(code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(cause, ssl.SSLCertVerificationError):
            # Not a passing fault: waiting will not make the certificate verifiable.
            raise ChatRefusedError("tls_certificate_unverified") from None
        raise ChatUnavailableError(type(error).__name__) from None
    except Exception as error:  # a cut response, an unreadable one: try again (review)
        raise ChatUnavailableError(type(error).__name__) from None


def _run(value: object) -> tuple[str, str] | None:
    match = _RUN.fullmatch(value) if isinstance(value, str) else None
    return (match.group(1), match.group(2)) if match else None


def read_request(kind: str, payload: Mapping[str, Any]) -> GatewayEvent:
    """Turn a Socket Mode request into a neutral event; anything unexpected is ignored."""
    if kind != "interactive":
        return Ignored(kind)
    interaction = str(payload.get("type", "unknown"))
    try:
        if interaction == "block_actions":
            return _choice(payload)
        if interaction == "view_submission":
            return _reason(payload)
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return Ignored(interaction)


def _choice(payload: Mapping[str, Any]) -> GatewayEvent:
    [action] = payload["actions"]
    run = _run(action["value"])
    choice = {AGREE: "agree", DISAGREE: "disagree"}.get(action["action_id"])
    if run is None or choice is None:
        return Ignored("block_actions")
    container = payload["container"]
    return Choice(
        user=str(payload["user"]["id"]),
        job=run[0],
        run_id=run[1],
        choice="agree" if choice == "agree" else "disagree",
        ref=MessageRef(str(container["channel_id"]), str(container["message_ts"])),
        trigger=str(payload["trigger_id"]),
    )


def _reason(payload: Mapping[str, Any]) -> GatewayEvent:
    view = payload["view"]
    if view["callback_id"] != REASON_VIEW:
        return Ignored("view_submission")
    target, channel, ts = str(view["private_metadata"]).split(" ")
    run = _run(target)
    if run is None:
        return Ignored("view_submission")
    value = view["state"]["values"][REASON_VIEW]["reason"].get("value")
    return Reason(
        user=str(payload["user"]["id"]),
        job=run[0],
        run_id=run[1],
        reason=str(value) if value is not None else None,
        ref=MessageRef(channel, ts),
    )


REJECTED: Final = frozenset(
    {"invalid_auth", "not_authed", "token_revoked", "account_inactive", "not_allowed_token_type"}
)
"""Errors that no retry can fix: the gateway stops for good (research R6)."""

CHECK_EVERY: Final = 5.0
_BACKOFF: Final = (5.0, 10.0, 20.0, 40.0, 60.0)


def _socket_client(app_token: str, bot_token: str) -> SocketModeClient:
    return SocketModeClient(
        app_token=app_token,
        web_client=_web_client(bot_token),  # its TLS context also serves the WebSocket
        logger=_LIBRARY,
        auto_reconnect_enabled=False,  # reconnection is ours, so a revoked token is seen
    )


class SlackGateway:
    """The ``Gateway`` port on Socket Mode: an outward WebSocket, no public address."""

    def __init__(
        self,
        app_token: str,
        bot_token: str,
        client: Callable[[str, str], SocketModeClient] = _socket_client,
        check_every: float = CHECK_EVERY,
        backoff: tuple[float, ...] = _BACKOFF,
    ) -> None:
        self._app_token = app_token
        self._bot_token = bot_token
        self._make = client
        self._every = check_every
        self._backoff = backoff
        self._stopped = threading.Event()
        self._seen = False

    def stop(self) -> None:
        """Ask ``serve`` to return."""
        self._stopped.set()

    def serve(
        self,
        handle: Callable[[GatewayEvent], None],
        state: Callable[[GatewayState, str | None], None],
    ) -> int:
        """Stay connected, handing each request to ``handle``; 0 when stopped for good."""
        client = self._make(self._app_token, self._bot_token)

        def listen(_: object, request: SocketModeRequest) -> None:
            # Acknowledge at once: Slack waits 3 seconds; the handling may take longer.
            client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
            handle(read_request(request.type, request.payload))

        client.socket_mode_request_listeners.append(listen)
        failures = 0
        trouble: str | None = None  # kept across retries, so the log changes only with it
        try:
            while not self._stopped.is_set():
                if client.is_connected():
                    failures, trouble = 0, None
                    state("connected", None)
                    self._stopped.wait(self._every)
                    continue
                if trouble is None:
                    trouble = "disconnected" if failures == 0 and self._seen else None
                state("connecting", trouble)
                try:
                    client.connect_to_new_endpoint(force=True)
                    self._seen = True
                    continue
                except SlackApiError as error:
                    code = str(error.response.get("error") or "unknown_error")
                    if code in REJECTED:
                        state("stopped", f"token rejected ({code})")
                        return 0
                    trouble = f"cannot connect ({code})"
                except Exception as error:  # any network trouble: wait and try again
                    trouble = f"cannot connect ({type(error).__name__})"
                state("connecting", trouble)
                self._stopped.wait(self._backoff[min(failures, len(self._backoff) - 1)])
                failures += 1
            return 0
        finally:
            client.close()
