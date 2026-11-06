# SPDX-License-Identifier: Apache-2.0
"""The Slack adapter: sending, errors, payloads and logs (spec 008; research R2 to R5).

A fake ``WebClient`` stands in for Slack; no test contacts it.
"""

import json
import logging
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

from opscout.adapters.slack import SlackChat, SlackGateway, blocks_of, read_request
from opscout.core.chat import (
    ChatMessage,
    ChatRefusedError,
    ChatUnavailableError,
    Choice,
    Ignored,
    MessageRef,
    Reason,
)
from tests.unit.chat.fakes import CHANNEL, TOKEN_SENTINEL, USER

PAYLOADS = Path(__file__).parent / "payloads"
RUN = "20261105T094500Z-a1b2c3"
REF = MessageRef(CHANNEL, "1762336800.000100")
RESULT = ChatMessage(
    markdown="# opscout check\n\nAll good.",
    notification="opscout check",
    buttons=f"check/{RUN}",
    context=f"opscout check, run {RUN}",
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


def slack_error(code: str, status: int = 200, retry_after: str | None = None) -> SlackApiError:
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = SlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/chat.postMessage",
        req_args={},
        data={"ok": False, "error": code},
        headers=headers,
        status_code=status,
    )
    return SlackApiError(f"The request to the Slack API failed: {code}", response)  # type: ignore[no-untyped-call]


@dataclass
class FakeWebClient:
    """Records calls; raises ``fail`` on the next call when set."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: Exception | None = None

    def _call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, kwargs))
        if self.fail is not None:
            raise self.fail
        return {"ok": True, "channel": {"id": CHANNEL}} if name == "conversations_open" else {
            "ok": True, "channel": CHANNEL, "ts": "1762336800.000100"
        }  # fmt: skip

    def conversations_open(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("conversations_open", **kwargs)

    def chat_postMessage(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802  (Slack's name)
        return self._call("chat_postMessage", **kwargs)

    def chat_update(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("chat_update", **kwargs)

    def views_open(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("views_open", **kwargs)


def chat(client: FakeWebClient) -> SlackChat:
    return SlackChat(token=lambda: TOKEN_SENTINEL, client=lambda token: client)  # type: ignore[arg-type,return-value]


# Sending (FR-006, FR-007, FR-010)


@spec("FR-006")
def test_a_message_opens_the_dm_then_posts_to_it() -> None:
    client = FakeWebClient()
    ref = chat(client).send(USER, RESULT)
    assert ref == REF
    (open_name, opened), (post_name, posted) = client.calls
    assert (open_name, opened) == ("conversations_open", {"users": USER})
    assert post_name == "chat_postMessage"
    assert posted["channel"] == CHANNEL
    assert posted["text"] == "opscout check"
    assert posted["blocks"] == blocks_of(RESULT)
    chat_ = chat(client)
    chat_.send(USER, RESULT)
    chat_.send(USER, RESULT)
    assert [name for name, _ in client.calls].count("conversations_open") == 2


@spec("FR-009")
def test_the_blocks_of_a_result_and_of_a_notice() -> None:
    markdown, actions, context = blocks_of(RESULT)
    assert markdown == {"type": "markdown", "text": RESULT.markdown}
    assert actions["type"] == "actions"
    assert [(e["action_id"], e["value"]) for e in actions["elements"]] == [
        ("opscout_agree", f"check/{RUN}"),
        ("opscout_disagree", f"check/{RUN}"),
    ]
    assert context == {
        "type": "context",
        "block_id": "opscout_context",
        "elements": [{"type": "plain_text", "text": f"opscout check, run {RUN}"}],
    }
    notice = ChatMessage(markdown="x", notification="x")
    assert blocks_of(notice) == [{"type": "markdown", "text": "x"}]


@spec("FR-007")
@pytest.mark.parametrize(
    ("failure", "retry_after"),
    [
        (urllib.error.URLError("offline"), None),
        (TimeoutError("timed out"), None),
        (slack_error("ratelimited", 429, "7"), 7.0),
        (slack_error("internal_error", 500), None),
        (slack_error("fatal_error"), None),
        (slack_error("service_unavailable", 503), None),
        (slack_error("request_timeout"), None),
    ],
)
def test_passing_failures_are_unavailable(failure: Exception, retry_after: float | None) -> None:
    client = FakeWebClient(fail=failure)
    with pytest.raises(ChatUnavailableError) as error:
        chat(client).send(USER, RESULT)
    assert error.value.retry_after == retry_after


@spec("FR-007")
@pytest.mark.parametrize(
    "code",
    [
        "invalid_auth", "token_revoked", "account_inactive", "user_not_found", "missing_scope",
        "channel_not_found", "invalid_blocks", "something_new",
    ],
)  # fmt: skip
def test_other_errors_are_refusals(code: str) -> None:
    client = FakeWebClient(fail=slack_error(code))
    with pytest.raises(ChatRefusedError) as error:
        chat(client).send(USER, RESULT)
    assert error.value.code == code
    assert TOKEN_SENTINEL not in str(error.value)


@spec("FR-011")
def test_the_slack_sdk_logs_are_silenced(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    library = logging.getLogger("slack_sdk")
    assert library.propagate is False
    assert logging.getLogger("slack_sdk.web.base_client").getEffectiveLevel() > logging.CRITICAL
    assert logging.getLogger("slack_sdk.socket_mode").getEffectiveLevel() > logging.CRITICAL
    client = FakeWebClient(fail=slack_error("invalid_auth"))
    with pytest.raises(ChatRefusedError):
        chat(client).send(USER, RESULT)
    logging.getLogger("slack_sdk.web.base_client").error("payload %s", RESULT.markdown)
    assert all(
        TOKEN_SENTINEL not in record.getMessage() and "All good" not in record.getMessage()
        for record in caplog.records
    )


# Updating and the reason dialog (FR-014, FR-016)


@spec("FR-015")
def test_an_update_sends_the_whole_message_again() -> None:
    client = FakeWebClient()
    chosen = ChatMessage(
        markdown=RESULT.markdown, notification="x", buttons=RESULT.buttons,
        context="Agreed on 2026-11-05 10:02",
    )  # fmt: skip
    chat(client).update(REF, chosen)
    [(name, kwargs)] = client.calls
    assert name == "chat_update"
    assert (kwargs["channel"], kwargs["ts"]) == (CHANNEL, "1762336800.000100")
    assert kwargs["blocks"] == blocks_of(chosen)
    assert kwargs["blocks"][1]["type"] == "actions"


@spec("FR-016")
def test_the_reason_dialog() -> None:
    client = FakeWebClient()
    chat(client).open_reason("1111.2222.example", "check", RUN, REF)
    [(name, kwargs)] = client.calls
    assert name == "views_open"
    assert kwargs["trigger_id"] == "1111.2222.example"
    view = kwargs["view"]
    assert view["callback_id"] == "opscout_reason"
    assert view["private_metadata"] == f"check/{RUN} {CHANNEL} 1762336800.000100"
    [block] = view["blocks"]
    assert block["optional"] is True
    assert block["block_id"] == "opscout_reason"
    assert block["element"]["action_id"] == "reason"
    assert block["element"]["max_length"] == 500
    assert block["element"]["multiline"] is True


# Payloads (FR-014)


def payload(name: str) -> tuple[str, dict[str, Any]]:
    data = json.loads((PAYLOADS / name).read_text(encoding="utf-8"))
    return data["type"], data["payload"]


@spec("FR-014")
def test_payloads_become_neutral_events() -> None:
    assert read_request(*payload("agree.json")) == Choice(
        user=USER, job="check", run_id=RUN, choice="agree", ref=REF, trigger="1111.2222.example"
    )
    disagree = read_request(*payload("disagree.json"))
    assert isinstance(disagree, Choice)
    assert disagree.choice == "disagree"
    other = read_request(*payload("other_user.json"))
    assert isinstance(other, Choice)
    assert other.user == "UEXAMPLE02"
    assert read_request(*payload("reason.json")) == Reason(
        user=USER, job="check", run_id=RUN, reason="  The note named the wrong day.  ", ref=REF
    )
    empty = read_request(*payload("empty_reason.json"))
    assert isinstance(empty, Reason)
    assert empty.reason is None


@spec("FR-014")
@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("foreign_action.json", "block_actions"),
        ("bad_value.json", "block_actions"),
        ("events_api.json", "events_api"),
    ],
)
def test_anything_else_is_ignored(name: str, kind: str) -> None:
    assert read_request(*payload(name)) == Ignored(kind)
    assert read_request("hello", {}) == Ignored("hello")
    assert read_request("interactive", {"type": "shortcut"}) == Ignored("shortcut")
    assert read_request("interactive", {"type": "block_actions", "actions": "x"}) == Ignored(
        "block_actions"
    )


# The gateway (FR-012, US5 scenarios 3 and 5)


@dataclass
class FakeSocketClient:
    """A Socket Mode client whose connections follow a script; it stops the gateway at the end."""

    connects: list[Exception | None]
    checks_connected: int = 2
    socket_mode_request_listeners: list[Any] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    connected: bool = False
    closed: bool = False
    gateway: SlackGateway | None = None

    def is_connected(self) -> bool:
        if self.connected:
            self.checks_connected -= 1
            if self.checks_connected == 0:
                self.connected = False  # the network drops once
            if self.checks_connected < -1 and self.gateway is not None:
                self.gateway.stop()
        return self.connected

    def connect_to_new_endpoint(self, force: bool = False) -> None:
        outcome = self.connects.pop(0) if self.connects else None
        if outcome is not None:
            raise outcome
        self.connected = True

    def send_socket_mode_response(self, response: Any) -> None:
        self.order.append("ack")
        self.responses.append(response.envelope_id)

    def close(self) -> None:
        self.closed = True


def gateway(client: FakeSocketClient) -> SlackGateway:
    made = SlackGateway(
        TOKEN_SENTINEL, TOKEN_SENTINEL, client=lambda app, bot: client,  # type: ignore[arg-type,return-value]
        check_every=0, backoff=(0,),
    )  # fmt: skip
    client.gateway = made
    return made


@spec("FR-012")
def test_the_gateway_reconnects_by_itself() -> None:
    client = FakeSocketClient(connects=[urllib.error.URLError("offline"), None, None])
    states: list[tuple[str, str | None]] = []
    assert gateway(client).serve(lambda event: None, lambda s, r: states.append((s, r))) == 0
    assert states[:4] == [
        ("connecting", None),
        ("connecting", "cannot connect (URLError)"),
        ("connecting", "cannot connect (URLError)"),
        ("connected", None),
    ]
    assert ("connecting", "disconnected") in states
    assert states[-1] == ("connected", None)
    assert client.closed is True


@spec("FR-012")
def test_a_rejected_token_stops_the_gateway_for_good() -> None:
    client = FakeSocketClient(connects=[slack_error("invalid_auth")])
    states: list[tuple[str, str | None]] = []
    assert gateway(client).serve(lambda event: None, lambda s, r: states.append((s, r))) == 0
    assert states == [("connecting", None), ("stopped", "token rejected (invalid_auth)")]
    assert TOKEN_SENTINEL not in repr(states)


@spec("FR-014")
def test_each_request_is_acknowledged_before_it_is_handled() -> None:
    from slack_sdk.socket_mode.request import SocketModeRequest

    client = FakeSocketClient(connects=[], checks_connected=1)
    handled: list[object] = []

    def handle(event: object) -> None:
        client.order.append("handle")
        handled.append(event)

    made = gateway(client)
    made.stop()
    made.serve(handle, lambda s, r: None)
    [listen] = client.socket_mode_request_listeners
    kind, data = payload("agree.json")
    listen(client, SocketModeRequest(type=kind, envelope_id="envelope-1", payload=data))
    assert client.order == ["ack", "handle"]
    assert client.responses == ["envelope-1"]
    assert isinstance(handled[0], Choice)


@spec("FR-007")
def test_an_unverifiable_certificate_is_a_refusal_not_a_wait() -> None:
    import ssl

    failure = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
    with pytest.raises(ChatRefusedError) as error:
        chat(FakeWebClient(fail=failure)).send(USER, RESULT)
    assert error.value.code == "tls_certificate_unverified"


@spec("FR-006")
def test_slack_is_reached_through_the_system_s_certificates() -> None:
    import truststore

    from opscout.adapters.slack import _socket_client, _web_client

    assert isinstance(_web_client("xoxb-example").ssl, truststore.SSLContext)
    socket = _socket_client("xapp-example", "xoxb-example")
    try:
        assert isinstance(socket.web_client.ssl, truststore.SSLContext)
        assert socket.auto_reconnect_enabled is False
    finally:
        socket.close()


@spec("FR-007")
def test_any_other_error_of_a_call_is_a_passing_fault() -> None:
    import http.client

    with pytest.raises(ChatUnavailableError):
        chat(FakeWebClient(fail=http.client.IncompleteRead(b"x"))).send(USER, RESULT)

    class Broken(FakeWebClient):
        def conversations_open(self, **kwargs: Any) -> dict[str, Any]:
            return {"ok": True}  # no channel: a response we cannot read

    with pytest.raises(ChatUnavailableError):
        chat(Broken()).send(USER, RESULT)


@spec("FR-019")
def test_connection_errors_are_named_and_a_wrong_token_type_stops() -> None:
    client = FakeSocketClient(connects=[slack_error("not_allowed_token_type")])
    states: list[tuple[str, str | None]] = []
    assert gateway(client).serve(lambda event: None, lambda s, r: states.append((s, r))) == 0
    assert states[-1] == ("stopped", "token rejected (not_allowed_token_type)")

    client = FakeSocketClient(connects=[slack_error("some_server_error"), None])
    states = []
    gateway(client).serve(lambda event: None, lambda s, r: states.append((s, r)))
    assert ("connecting", "cannot connect (some_server_error)") in states
    client = FakeSocketClient(connects=[urllib.error.URLError("offline"), None])
    states = []
    gateway(client).serve(lambda event: None, lambda s, r: states.append((s, r)))
    assert ("connecting", "cannot connect (URLError)") in states
