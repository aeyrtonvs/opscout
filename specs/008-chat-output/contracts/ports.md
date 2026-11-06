# Contract: ports

New, in `opscout.core.chat`:

```python
class Chat(Protocol):
    def send(
        self, user: str, message: ChatMessage
    ) -> MessageRef: ...  # ChatUnavailableError | ChatRefusedError
    def update(self, ref: MessageRef, message: ChatMessage) -> None: ...
    def open_reason(self, trigger: str, job: str, run_id: str, ref: MessageRef) -> None: ...


class Gateway(Protocol):
    def serve(
        self,
        handle: Callable[[GatewayEvent], None],
        state: Callable[[GatewayState, str | None], None],
    ) -> int: ...
    def stop(self) -> None: ...
```

Changed, in `opscout.core.daemon` (spec 007):

```python
class Delivery(Protocol):
    def preflight(self) -> None: ...  # raises DeliveryError before any model run
    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> Receipt: ...


class RunStore(Protocol):
    ...  # as in spec 007, plus:

    def get(self, job: str, run_id: str) -> RunRecord | None: ...
```

`Ports` gains `alert: Callable[[str, str, str], MessageRef | None] | None`, the failure
notice (FR-024). The click handler reads a delivered text through `LocalOutbox.text(job,
run_id)`, to render the message again; the gateway's lock and state are `GatewayFiles`.

| Port | Adapter | Fake |
|---|---|---|
| `Chat` | `adapters.slack.SlackChat` (`WebClient`) | records sends and updates; can be made unavailable or refusing |
| `Gateway` | `adapters.slack.SlackGateway` (built-in `SocketModeClient`) | feeds events |
| `Delivery` | `adapters.run_files.LocalOutbox`, and `services.chat.ChatDelivery` around it | in-memory |

The payload parsing (`adapters.slack.read_request`) is tested on hand-written payloads in
`tests/unit/chat/payloads/` that follow Slack's documented shapes, with fake ids.
