# Research: Chat output

Checked on 2026-11-05 against docs.slack.dev (Socket Mode, app manifest, chat.postMessage,
Block Kit markdown block, scopes), the `slack-sdk` 3.45.0 wheel, and PyPI.

## R1. Library: `slack-sdk`, its built-in Socket Mode client (constitution: a reason per dependency)

**Facts**: `slack-sdk` 3.45.0 (2026-10-01, MIT) has no required dependency (aiohttp and
websockets are optional extras), ships `py.typed`, and includes
`slack_sdk.socket_mode.builtin.SocketModeClient`, a standard-library WebSocket client with
`auto_reconnect_enabled=True` and a ping every 5 s by default, plus `WebClient` for the Web
API. 3.46.0 (2026-10-30) is newer than the 7-day cooldown Dependabot keeps. `slack-bolt`
1.30.0 is a framework on top of `slack-sdk`.

**Decision**: add `slack-sdk>=3.45,<4`, locked at 3.45.0; use `WebClient` and the built-in
`SocketModeClient` only. The `slack_sdk` loggers are silenced (no handler, no propagation):
at debug level they can print payloads, and a connection URL carries a short-lived ticket.
The gateway logs its own lines only (R7). A test pins it: the `slack_sdk` logger has no
handler and does not propagate, and a simulated send and connection leave no token or
message text in any captured log record.

**Found in the live check** (2026-11-05): python.org's Python on macOS ships without a
certificate store, so the default TLS context could not verify Slack
(`CERTIFICATE_VERIFY_FAILED`), and the run retried for 10 minutes. **Decision**: add
`truststore>=0.10,<1` (0.10.5, MIT, no dependency, already in `uv.lock` through the
development tools), whose context asks the operating system's own verifier (the macOS
keychain, Windows, the Linux system bundle), so a company's certificate authority works
too; both Slack clients use it (the Socket Mode client reuses the Web client's context). A
certificate that cannot be verified is a refusal (`tls_certificate_unverified`), not a
passing fault: no wait fixes it. `certifi` was rejected: its fixed Mozilla bundle ignores a
company's certificate authority.

**Alternatives rejected**: `slack-bolt` (a framework and a second dependency for two
handlers); a hand-written WebSocket client (reconnection, ping and the hello handshake are
what the SDK already does); the `websockets` or `aiohttp` extras (async adds nothing for one
connection).

## R2. The app manifest and its permissions (FR-004)

**Facts**: a bot posts a direct message with `chat.postMessage` and the `chat:write` scope;
the documentation recommends the DM channel id from `conversations.open` (scope
`im:write`) over passing the user id, which older pages say lands in the Slackbot DM.
`chat.update` needs `chat:write`; `views.open` needs no scope (it needs a trigger id from
an interaction). Socket Mode needs `settings.socket_mode_enabled: true` and an app-level
token (`xapp-…`) with `connections:write`; interactive payloads come over the socket when
`settings.interactivity.is_enabled: true`, with no request URL.
`features.app_home.messages_tab_read_only_enabled: true` stops users writing to the app.

**Decision**: `deploy/slack/opscout-app-manifest.yaml`:

```yaml
display_information:
  name: opscout
  description: Delivers your opscout jobs by direct message.
features:
  bot_user:
    display_name: opscout
    always_online: false
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: true
oauth_config:
  scopes:
    bot: [chat:write, im:write]
settings:
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
```

No `event_subscriptions`: the app receives no message, mention or channel event, only the
interactions on its own messages. A test reads the manifest and holds the bot scopes to
exactly `chat:write` and `im:write`, with no event subscription and no request URL. The
app-level token's scope, `connections:write`, is chosen when the token is created
(quickstart).

## R3. The message (FR-008, FR-009, FR-024)

**Facts**: the `markdown` block (Block Kit, 2025) takes standard Markdown and Slack renders
it; all `markdown` blocks of one message share a 12,000-character limit, and one block may
become several after translation. A message also takes `text`, used for notifications.

**Decision**: a message is, in order:

1. one `markdown` block with the job's text, unchanged; a text over 11,000 characters is
   cut at the last line break before that, followed by
   `_Shortened; the full text is in <outbox file>._`;
2. for a result only, an `actions` block with two buttons, `Agree` (`opscout_agree`) and
   `Disagree` (`opscout_disagree`), each with the value `<job>/<run-id>`;
3. for a result only, a `context` block `opscout <job>, run <run-id>` (the delivery knows the run, not its period), which a click
   replaces with the choice (R5).

`text` (the notification) is the first line of the job's text without Markdown marks, at
most 150 characters. A notice (refused, inconclusive, failed) has only the `markdown` block.
The rendering is pure (`services/chat.py`, `render_message`), so it is tested without Slack.

## R4. Sending, and the 10-minute retry (FR-006, FR-007, FR-024)

**Facts**: Web API errors come as `SlackApiError` with an `error` code; rate limiting is
HTTP 429 `ratelimited` with `Retry-After`; network faults raise `URLError` or socket
timeouts.

**Decision**:

- The adapter opens the DM (`conversations.open users=<id>`) and posts to it; it returns
  the channel id and the message `ts` as the reference.
- It raises `ChatUnavailableError(retry_after)` for network faults, HTTP 5xx, `ratelimited`,
  `internal_error`, `fatal_error`, `service_unavailable` and `request_timeout`; and
  `ChatRefusedError(code)` for any other error code (`invalid_auth`, `token_revoked`,
  `account_inactive`, `user_not_found`, `missing_scope`, `channel_not_found`, `invalid_blocks`
  and anything unknown), so an unknown error never loops for 10 minutes. Any other exception
  of a call (a cut response, one that cannot be read) is `ChatUnavailableError`, so it never
  escapes the run without a record.
- A delivery whose message failed keeps the outbox file in the record (`delivery`).
- `ChatDelivery` (services) writes the outbox copy first, then sends; on `ChatUnavailableError`
  it waits `retry_after`, else 5, 10, 20, 40, 60, 60… seconds, until 600 seconds have passed
  since the first try; then, or on `ChatRefusedError`, it raises `DeliveryError`, so the run is
  `failed` (spec 007, FR-005). The clock and the sleep are injected.
- The run's lock is held through the retries, as for any run (spec 007, FR-004).

## R5. Clicks, the reason dialog, and the record (FR-014 to FR-017)

**Facts**: a button click arrives over the socket as an `interactive` envelope with a
`block_actions` payload: `user.id`, `actions[].action_id` and `value`, `trigger_id`,
`container.channel_id`, `container.message_ts`, and the `message` with its `blocks`. A
modal opened with `views.open` (the trigger id lasts 3 seconds) returns a `view_submission`
payload with `user.id`, `view.callback_id`, `view.private_metadata` and `view.state.values`.
Every envelope is acknowledged with its `envelope_id` within 3 seconds.

**Decision**:

- The adapter acknowledges every envelope at once, then turns the payload into a neutral
  event: `Choice(user, job, run_id, choice, ref, trigger)`,
  `Reason(user, job, run_id, reason, ref)`, or `Ignored(kind)`; anything else, including a
  value that is not `<job>/<run-id>` in the run id's format, is `Ignored`.
- `handle_event` (services) acts only on `Choice` and `Reason` from the configured user:
  - `Choice(agree)`: set the record's agreement to `agree`, now, no reason;
  - `Choice(disagree)`: open the reason dialog first, while the click's trigger id is
    still valid (3 seconds), then set `disagree`, now, no reason;
  - `Reason`: set `disagree`, now, with the reason (trimmed; empty means none);
  - an agreement equal to the stored one (choice and reason) leaves the record as it is;
  - then the message is rendered again from the run's outbox file and record, with the
    context line `Agreed on 2026-11-05 10:02` or `Disagreed on …: <reason>`, and replaces
    the old one (`chat.update`), so the buttons stay; when the outbox file cannot be read,
    the record is still updated and the message is left as it is. Re-rendering avoids
    keeping Slack's blocks, which a dialog submission does not carry.
- The record is found by job and run id; when it is not there yet (a click within moments
  of the delivery, before the record is written), the handler looks again for up to 5
  seconds. A record still missing or unreadable stores nothing, and the context block says
  `This choice could not be recorded (run <run-id> not found).`
- The record is written in one step (`os.replace`), and the clicks of one run are handled
  one at a time (a lock per run): the chat client hands events to a pool of threads, and
  two quick clicks must not both read the record before either writes it.
- The same button again leaves the record as it is: a second Disagree keeps the reason
  given before (it still opens the dialog, to change it).
- The dialog has one optional multi-line input, at most 500 characters (Slack enforces the
  maximum), with `private_metadata` `<job>/<run-id> <channel> <ts>`, so the submission can
  update the message.

## R6. The gateway process (FR-012, FR-013, FR-018)

**Decision**:

- The built-in client's own reconnection is turned off: it would retry a revoked token every
  5 seconds without saying so. `SlackGateway.serve` checks the connection every 5 seconds
  and reconnects itself, with waits growing to 60 seconds on network errors; a rejected
  token (`invalid_auth`, `not_authed`, `token_revoked`, `account_inactive`,
  `not_allowed_token_type`, the bot token stored as the app-level one) stops it.
- `opscout gateway --config <dir>` loads the configuration, takes an exclusive `flock` on
  `<data>/gateway.lock` (a second start prints `opscout gateway: another gateway is
  running` and exits 0), resolves both tokens, connects, and blocks.
- It is the scheduled job `gateway` (label `opscout.gateway`) in the property list:
  `RunAtLoad: true`, `KeepAlive: {SuccessfulExit: false}`, `ThrottleInterval: 30`, no
  `StartCalendarInterval`. launchd starts it at login and again whenever it exits with an
  error; it exits 0 only when it must not be restarted (a token rejected, chat no longer
  configured, another gateway running), and status says why (R7). On an invalid
  configuration it writes `stopped`, reason `configuration invalid`, waits 5 minutes and
  exits 1, so launchd tries again without flooding the log, and a fixed configuration is
  picked up by itself.
- `launchctl bootout` returns before a running job has stopped (the gateway takes a few
  seconds to close its connection), and a bootstrap right after it would fail, so
  `Launchctl.unload` waits, checking every half second, until launchd no longer has the job,
  for up to 15 seconds (found in the live check).
- `ScheduledJob` gains `keep_alive`; `wanted_jobs` adds the gateway when the configuration
  has `daemon.chat`, so install, uninstall, status and the confirmation code treat it like a
  job (spec 007). `gateway` becomes a reserved job name.

## R7. The gateway's state and log (FR-019 to FR-021)

**Decision**: every 60 seconds while connected, and on each change, the gateway writes
`<data>/gateway.json` in one step: `{"state": "connected" | "connecting" | "stopped",
"since": …, "last_seen": …, "reason": …, "handled": n, "ignored": n}`. `reason` names a
kind (`token rejected`, `configuration invalid`), never a token or a message. Its log
(`<log>/gateway.log`, through launchd) has one line per state change and per error kind.

`since` changes only with the state, so a gateway retrying for hours keeps the time it lost
the connection; `last_seen` shows it is alive. A gateway asked to stop (logout, uninstall,
a signal) writes `stopped`, reason `asked to stop`. While it retries, the reason is kept
(`cannot connect (<code or error type>)`), so the log gains a line only when it changes.

- `daemon status` adds `gateway  always  installed, loaded  connected since 09:12`; or
  `not connected since <since>` (retrying), `not running; last seen <time>` (connected but
  silent for 15 minutes: the process is gone), `stopped: <reason>; last seen <time> (run
  opscout daemon install to start it again; …)`, `never connected`, or what install would
  change.
- The SessionStart notice adds, when chat is configured, `- gateway: not installed`,
  `never connected` (15 minutes after the install), `not connected since <since>` (retrying
  for more than 15 minutes), `not running since <last seen>` (silent for 15 minutes) or
  `stopped: <reason> (run opscout daemon install to start it again)`.
- A gateway that stopped for good stays loaded, so its property list is unchanged; install
  then adds a `restart` change (`launchctl kickstart -k`), confirmed like any other, and
  status names it. A change of the chat setting (user, tokens' references) changes a
  fingerprint in the gateway's environment, so install reloads it: the gateway reads its
  configuration once, at start (independent review).

## R8. Tokens (FR-002, FR-011)

**Decision**: `KEYCHAIN_ITEMS` gains `slack_bot_token` and `slack_app_token`. `daemon.chat`
requires both in `daemon.secrets` (a model validator names the missing one). The bot token
is resolved by `ChatDelivery.preflight()`, before any model run, so a missing token fails
the run first (US5 scenario 1); the gateway resolves both at start. Neither is in the
runner's profile, so neither reaches `claude` (the child's environment is still only the
allow-list plus the job's declared secrets, spec 007 R1). The SC-004 sentinel scan gains a
chat token sentinel and a reason sentinel.

## R9. Ports and the record (FR-022)

**Decision**:

- New port `Chat` in `core/chat.py`: `send(user, message) -> MessageRef`,
  `update(ref, message)`, `open_reason(trigger, job, run_id, ref)`; neutral `ChatMessage`
  (markdown, notification text, buttons, context line); `ChatUnavailableError` and `ChatRefusedError`.
  The Socket Mode listener is the adapter's `Gateway.serve(handler)`; the handler is
  `services.chat.handle_event`.
- `Delivery.deliver` returns a `Receipt` (`location`, `chat: MessageRef | None`) and gains
  `preflight()`; `LocalOutbox` returns `Receipt(path, None)` and has nothing to check.
  The record gains `chat` (the message reference) and `agreement` becomes
  `Agreement | None` (`choice`, `at`, `reason`); both additive, so `record_version` stays 1
  and spec 007's records still read.
- `Ports` gains `alert`, used for the failure notice (FR-024): a run that ends `failed` for
  a reason other than its own delivery sends a notice through it; with chat off it is
  absent and nothing is sent, as in spec 007.
- `RunStore` gains `get(job, run_id)`.
- Adapters: `adapters/slack.py` (`SlackChat`, `SlackGateway`), built only in
  `entrypoints/daemon.py`; tests use a fake `Chat` and feed `handle_event` neutral events,
  and test the payload parsing on hand-written payloads that follow the documented shapes,
  with fake ids (`UEXAMPLE01`, `DEXAMPLE01`).

## R10. Live proof (FR-023)

**Decision**: on the maintainer's workspace, after the user creates the app from the
manifest and stores the tokens themself: install with a temporary configuration naming the
user's member id; a scheduled `check` run delivers a direct message; a click on it is
stored in the record; `Disagree` with a reason; the gateway reconnects after Wi-Fi off and
on; uninstall. The user's member id lives only in the temporary configuration and their
private configuration, never in this repository.

## R11. Housekeeping in this pull request

PLAN.md's status line says spec 007 is merged; §9 gains an item: the spec-004 push-guard
timing test (1 s) measured 1.09 s once on a hosted macOS runner under coverage (run
42123108217); decide whether that step should time it.
