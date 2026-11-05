# Contract: the ports

Ports are `typing.Protocol` classes in `opscout.core.daemon`; each has a fake in
`tests/unit/daemon/fakes.py`. Adapters live in `opscout.adapters` and are built only by the
composition root, `opscout.entrypoints.daemon` (ADR-0011, ADR-0021). `Delivery` is the
port the spec calls the output port.

```python
class Runner(Protocol):
    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult: ...


class RunStore(Protocol):
    def hold(self, job: str, period: str) -> AbstractContextManager[bool]: ...  # False: busy
    def delivered(self, run_key: str) -> RunRecord | None: ...
    def write(self, record: RunRecord) -> None: ...
    def records(self, job: str | None, limit: int) -> list[RunRecord]: ...


class Delivery(Protocol):
    def deliver(self, job: str, run_id: str, kind: DeliveryKind, text: str) -> str: ...


class SecretStore(Protocol):
    def status(self, name: str, ref: KeychainRef) -> SecretStatus: ...
    def resolve(self, name: str, ref: KeychainRef) -> str: ...  # raises SecretError
    def store(self, name: str, ref: KeychainRef, value: str) -> None: ...


class Scheduler(Protocol):
    def installed(self) -> list[InstalledJob]: ...
    def installed_times(self) -> dict[str, datetime]: ...  # no service call (R10)
    def plan(self, wanted: Sequence[ScheduledJob]) -> PendingSchedule: ...
    def apply(self, pending: PendingSchedule) -> None: ...
```

The scheduler gets OS-neutral `ScheduledJob`s (program and arguments, weekday and time
pairs, log file, environment); the launchd adapter renders them as property lists. Its seam
to launchd is `ServiceManager` in `opscout.adapters.launchd` (`load(plist)`,
`unload(label)`, `is_loaded(label)`), not a core port, since only that adapter uses it
(FR-013). `ClaudeCliRunner` gets `compare_profile` from the composition root, since an
adapter does not import `services` (ADR-0011).

| Port | Adapter (this feature) | Fake |
|---|---|---|
| `Runner` | `adapters.claude_cli.ClaudeCliRunner`, which starts the executable through `subprocess.Popen` | a scripted runner; the adapter is tested against a fake `claude` script that prints recorded streams |
| `RunStore` | `adapters.run_files.FileRunStore` | in-memory |
| `Delivery` | `adapters.run_files.LocalOutbox` | in-memory list |
| `SecretStore` | `adapters.keychain.KeyringSecretStore` | in-memory; the adapter is tested on an in-memory `keyring` backend |
| `Scheduler` | `adapters.launchd.LaunchdScheduler` | in-memory |
| `ServiceManager` | `adapters.launchd.Launchctl` | records calls |

The recorded streams the contract tests read live in
`tests/unit/daemon/streams/` (sanitized from CLI 2.1.318): a tool-less success, an invalid
output, a budget error, a report with extra tools, one with a user plugin, one with an MCP
server, one with another permission mode, one with an older version, and one whose first
line is not the report. They keep only the fields the runner reads and a few around them;
the budget recording was made without a schema, so its report's `tools` was set to the
schema run's `[StructuredOutput]`.
