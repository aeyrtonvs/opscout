---
description: "Tasks for chat output (spec 008)"
---

# Tasks: Chat output

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md),
[contracts/ports.md](contracts/ports.md), [quickstart.md](quickstart.md)

**Tests**: mandatory and first; `@spec("FR-0NN")` with a helper bound to `"008"`, one
requirement per decorator (the traceability test reads them). Fakes for `Chat` and the
gateway's events; temporary directories for data, logs and agents; reserved values only
(`UEXAMPLE01`, `DEXAMPLE01`; the leak check refuses Slack ids whose second character is a
digit). No test contacts Slack.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/008-chat-output`: `uv run just fast` passes
- [X] T002 Add `slack-sdk>=3.45,<4` with `uv add`, locked at 3.45.0 (`uv lock
  --upgrade-package slack-sdk==3.45.0`), research R1; check that `mypy --strict` accepts
  `slack_sdk` (it ships `py.typed`)
- [X] T003 [P] Write the hand-written payloads in `tests/unit/chat/payloads/`, following
  Slack's documented shapes with fake ids: `agree.json` and `disagree.json`
  (`block_actions` from `UEXAMPLE01` on `DEXAMPLE01`), `other_user.json`,
  `foreign_action.json` (an action id that is not opscout's), `bad_value.json` (a value
  that is not `<job>/<run-id>`), `reason.json` and `empty_reason.json` (`view_submission`),
  `events_api.json` (an `events_api` envelope), and `tests/unit/chat/fakes.py` (a `Chat`
  that records sends, updates and dialogs and can be unavailable for N tries or refuse;
  a fake clock and sleep)

## Phase 2: Foundational — configuration, core types, the changed spec-007 ports

- [X] T004 Create `tests/unit/chat/test_traceability.py`: every FR-001 to FR-024 of the spec
  has a test marked with it (this test is marked FR-023), `xfail(strict=True)` until T041;
  a test marked FR-022 that the chat adapter module is under `opscout.adapters` (so spec
  007's forbidden contract covers it) and that `lint-imports` passes
- [X] T005 Write failing tests in `tests/unit/chat/test_config.py` (FR-001, FR-002, FR-003):
  `daemon.chat` optional and additive; `service` only `slack`; `user` "`U` or `W`, then 2–20
  capital letters or digits"; chat without `slack_bot_token` or `slack_app_token` in
  `daemon.secrets` refused, naming the missing one; the two names accepted by `secret set`
  and `check`; a job named `gateway` refused; the schema refuses what the loader refuses; a
  compatibility file
- [X] T006 Implement `ChatSetting` and `Daemon.chat`, the `KEYCHAIN_ITEMS` and reserved name
  changes in `src/opscout/core/config.py`; add
  `tests/unit/config_contract/compat/v1/chat.yaml`; regenerate the schema; T005 passes
- [X] T007 Write `src/opscout/core/chat.py` (`ChatMessage`, `MessageRef`, `Choice`,
  `Reason`, `Ignored`, `ChatUnavailableError(retry_after)`, `ChatRefusedError(code)`, the `Chat` and
  `Gateway` ports) and change `src/opscout/core/daemon.py`: `Receipt`, `Agreement`
  ("`choice` agree or disagree; `reason` at most 500 characters, null when empty"),
  `RunRecord.chat` and `RunRecord.agreement: Agreement | None` (both default null,
  `record_version` 1), `Delivery.preflight` and `deliver -> Receipt`, `RunStore.get`,
  `ScheduledJob.keep_alive`, `Ports.alert`
- [X] T008 Adapt spec 007 to the changed ports, its behavior unchanged:
  `LocalOutbox.deliver` returns `Receipt(path, None)` and `preflight` does nothing;
  `FileRunStore.get(job, run_id)`; `run_job` calls `preflight` before secrets and the model
  (a `DeliveryError` there is `failed`), stores `receipt.location` and `receipt.chat`;
  `tests/unit/daemon/fakes.py` and spec 007's tests updated; a test that a spec-007 record
  without `chat` still reads; `uv run just fast` passes

## Phase 3: User Story 1 — a job's result arrives as a direct message (P1) 🎯 MVP

**Goal**: deliveries reach the user by DM, `delivered` only after Slack accepted.
**Independent test**: a job through `ChatDelivery` with the fake `Chat`.

- [X] T009 [P] [US1] Write failing tests for `render_message` in
  `tests/unit/chat/test_render.py` (FR-008, FR-009, research R3): the text unchanged in the
  markdown field; a text over 11,000 characters cut at the last line break before it, with
  `_Shortened; the full text is in <file>._`; the notification is the first line without
  Markdown marks, at most 150 characters; a result has buttons `<job>/<run-id>` and the
  context line; a notice has neither
- [X] T010 [P] [US1] Write failing tests for `ChatDelivery` in
  `tests/unit/chat/test_delivery.py` (FR-006, FR-007, FR-010): the outbox file first, then
  one send to the configured user, the receipt with both; unavailable twice then accepted:
  delivered, waits 5 then 10 seconds; `retry_after` honored; unavailable past 600 seconds:
  `DeliveryError` naming "could not be reached for 10 minutes", outbox file kept; refused:
  `DeliveryError` naming the code, no retry; the recipient is always the configured user,
  whatever the text says; `preflight` resolves the bot token and turns a `SecretError` into
  a `DeliveryError`
- [X] T011 [US1] Implement `render_message` and `ChatDelivery` in
  `src/opscout/services/chat.py`; T009 and T010 pass
- [X] T012 [P] [US1] Write failing tests for `SlackChat.send` in
  `tests/unit/chat/test_slack.py` with a fake `WebClient` (FR-006, FR-007, research R2–R4):
  `conversations_open(users=…)`, then `chat_postMessage` to the returned `D…` channel with a
  `markdown` block, the `actions` and `context` blocks for a result, and `text`; the
  reference from `channel` and `ts`; network errors, HTTP 5xx, `ratelimited` (with
  `Retry-After`), `internal_error`, `fatal_error`, `service_unavailable`,
  `request_timeout` → `ChatUnavailableError`; `invalid_auth`, `token_revoked`,
  `account_inactive`, `user_not_found`, `missing_scope`, `channel_not_found`,
  `invalid_blocks` and an unknown code → `ChatRefusedError`; the `slack_sdk` logger has no
  handler and does not propagate, and no captured log record of a send holds the token or
  the text (research R1)
- [X] T013 [US1] Implement `SlackChat` in `src/opscout/adapters/slack.py`, silencing the
  `slack_sdk` loggers; T012 passes
- [X] T014 [US1] Write failing tests in `tests/unit/chat/test_commands.py` with fakes in the
  composition root (FR-003, FR-006, US1 scenarios 1, 4–6): `opscout run check` with chat
  configured delivers by DM and records `chat`; refused and inconclusive send a notice
  without buttons; without chat, spec 007's behavior; a missing bot token fails before the
  runner, naming `opscout secret set slack_bot_token`; the runner's environment holds
  neither Slack token (FR-011)
- [X] T015 [US1] Wire `ChatDelivery` and `SlackChat` in `src/opscout/entrypoints/daemon.py`
  when `daemon.chat` is set; T014 passes

**Checkpoint**: a result arrives by DM through the fakes.

## Phase 4: User Story 2 — the user records agreement (P1)

**Goal**: a click is stored in the run record and shown in the message.
**Independent test**: `handle_event` with neutral events, a memory store and the fake `Chat`.

- [X] T016 [P] [US2] Write failing tests for `handle_event` in
  `tests/unit/chat/test_gateway.py` (FR-015, FR-016, FR-017, US2 scenarios 1–6): agree
  stores `agree`, the time, no reason, and updates the context line to `Agreed on …`;
  disagree opens the reason dialog before anything else (its trigger lasts 3 seconds), then
  stores `disagree`, even when the record appears only after a wait; a reason sets it, trimmed, empty
  is none, over 500 characters refused; the other choice replaces the first; the same
  choice and reason again leave the record as it is (no write); a record that appears within
  5 seconds is found; one still missing stores nothing and the line says it could not be
  recorded; the record is written in one step
- [X] T017 [US2] Implement `handle_event` and the agreement update in
  `src/opscout/services/chat.py`; T016 passes
- [X] T018 [P] [US2] Write failing tests for `read_request` and `SlackChat.update` and
  `open_reason` in `tests/unit/chat/test_slack.py` (FR-014, research R5): each payload of
  T003 becomes the right event; the envelope is acknowledged before handling; `update`
  sends `chat_update` with the full message, buttons included; `open_reason` sends `views_open`
  with one optional input of at most 500 characters and `private_metadata`
  `<job>/<run-id> <channel> <ts>`
- [X] T019 [US2] Implement `read_request`, `SlackChat.update`, `open_reason` in
  `src/opscout/adapters/slack.py`; T018 passes

**Checkpoint**: an agreement click is stored through the fakes (exit criterion, in part).

## Phase 5: User Story 3 — only the user, only direct messages (P1)

**Goal**: one recipient, one clicker, two scopes, no chat content anywhere else.
**Independent test**: foreign users and events against `handle_event`; the manifest file.

- [X] T020 [P] [US3] Write failing tests in `tests/unit/chat/test_manifest.py` (FR-004):
  `deploy/slack/opscout-app-manifest.yaml` has bot scopes exactly `chat:write` and
  `im:write`, no user scopes, no `event_subscriptions`, no request URL, Socket Mode and
  interactivity on, the Messages tab read-only
- [X] T021 [US3] Write `deploy/slack/opscout-app-manifest.yaml` (research R2); T020 passes
- [X] T022 [US3] Write failing tests in `tests/unit/chat/test_gateway.py` (FR-010, FR-014,
  FR-016, US3 scenarios 1–3, 5): a click or a reason from another user stores nothing and
  answers nothing; `Ignored` events only count; a reason sentinel is in the record only,
  never in a log line or output; nothing from an event reaches a runner; then make them pass
  in `src/opscout/services/chat.py`

## Phase 6: User Story 4 — the user sets up chat once (P2)

**Goal**: the gateway installed, supervised and visible.
**Independent test**: install, install again, remove chat, install, with fakes.

- [X] T023 [P] [US4] Write failing tests in `tests/unit/daemon/test_launchd.py` and
  `tests/unit/chat/test_commands.py` (FR-013, research R6): with chat configured,
  `wanted_jobs` adds `opscout.gateway` running `… gateway --config <dir>`; its property list
  has `RunAtLoad`, `KeepAlive {SuccessfulExit: false}`, `ThrottleInterval 30` and no
  calendar; the change line reads `add opscout.gateway (always)`; a second install changes
  nothing (SC-005); chat removed removes it; uninstall removes it; without a scheduler (not
  macOS) a manual run still delivers by DM and installing says no scheduler is available
- [X] T024 [US4] Implement the keep-alive property list in `src/opscout/adapters/launchd.py`
  and the gateway entry in `wanted_jobs` and `describe_change` in
  `src/opscout/services/daemon.py`; T023 passes
- [X] T025 [P] [US4] Write failing tests for `opscout gateway` in
  `tests/unit/chat/test_commands.py` with a fake `Gateway` (FR-012, FR-018, FR-019): it
  takes `<data>/gateway.lock`, and a second start prints `another gateway is running` and
  exits 0; without `daemon.chat` it exits 0 with its line; it writes `gateway.json` on each
  state and every 60 seconds while connected; log lines name states and error kinds only; an
  invalid configuration does not connect, writes `stopped`, waits 5 minutes (a fake sleep)
  and exits 1
- [X] T026 [US4] Implement `SlackGateway` (built-in `SocketModeClient`, the handler in a
  thread, the state callback, reconnection left to the client) in
  `src/opscout/adapters/slack.py`, the gateway state file in
  `src/opscout/adapters/run_files.py`, and `opscout gateway` in
  `src/opscout/entrypoints/daemon.py` and `cli.py`; T025 passes
- [X] T027 [US4] Write failing tests, then implement, for the status line in
  `tests/unit/chat/test_commands.py` and `src/opscout/services/daemon.py` (FR-020):
  `gateway  always  installed, loaded  connected since …`, `not connected; last seen …`,
  `stopped: <reason>; last seen …`, `not installed`

## Phase 7: User Story 5 — chat failures are visible (P2)

- [X] T028 [P] [US5] Write failing tests in `tests/unit/chat/test_delivery.py` and
  `tests/unit/daemon/test_run_job.py` (FR-024, US5 scenario 2): with an alert, a run that
  ends `failed` for a runner, secret or time reason sends one notice (job, period, reason,
  `opscout daemon runs <job>`) without buttons; a run that failed in its own delivery or
  preflight sends none; without chat, none; the outcome stays `failed` and the period runs
  again
- [X] T029 [US5] Implement the alert in `src/opscout/services/daemon.py` and its wiring in
  `src/opscout/entrypoints/daemon.py`; T028 passes
- [X] T030 [P] [US5] Write failing tests in `tests/unit/chat/test_gateway.py` (US5 scenario
  3, FR-012): a rejected app-level token stops the gateway with exit 0 and state `stopped`,
  reason `token rejected`, the token never in the log; any other error exits 1
- [X] T031 [US5] Implement the stop rules in `src/opscout/adapters/slack.py` and
  `src/opscout/entrypoints/daemon.py`; T030 passes
- [X] T032 [US5] Write failing tests, then implement, for the SessionStart lines in
  `tests/unit/chat/test_session_notice.py` and `src/opscout/services/daemon.py` (FR-021):
  chat configured and the gateway not installed; `last_seen` more than 15 minutes old;
  `stopped`; nothing when connected or chat is off

## Phase 8: Polish and the live check

- [X] T033 [P] Write the setup in `docs/reference/daemon.md` (create the app from the
  manifest, install, the app-level token with `connections:write`, the member id, store
  both tokens, configure, install; the gateway, its log and state; agreement), the
  `daemon.chat` section in `docs/reference/configuration.md`, and a commented example in
  `example-config/config.yaml`; a test marked FR-005 that the reference names the manifest
  path and both `opscout secret set` commands
- [X] T034 [P] Extend the SC-004 scan in `tests/unit/daemon/test_zz_sentinel.py` to a chat
  token sentinel and a reason sentinel (FR-011)
- [X] T035 Update `docs/PLAN.md`: the status line (spec 007 merged, spec 008 in progress),
  the chat-output paragraph in §7, §9 (the push-guard timing item, research R11)
- [X] T036 The user creates the app and stores the tokens (quickstart steps 2–3); then run
  quickstart step 4 (a manual DM)
- [X] T037 Run quickstart step 5 (FR-023, SC-001, SC-002): a scheduled `check` DM, an Agree
  and a Disagree with a reason, each stored in the record
- [X] T038 Run quickstart steps 6–7 (SC-006): reconnection after the network returns;
  uninstall leaves no `opscout.*` entry
- [X] T039 Record the live results in the spec's Actuals and PLAN.md §7
- [X] T040 Run `uv run just check` and `uv run just coverage` (100 % on `core` and `services`)
- [X] T041 Remove the traceability `xfail`; set the spec's status to Implemented and record
  the effort

## Dependencies

1 → 2 → 3 (US1, MVP) → 4 (US2) → 5 (US3) → 6 (US4) → 7 (US5) → 8. Within a phase, tests
before their implementation. T026 needs T019 (the handler); T029 needs T015; T036–T038 need
every story and the user's setup; T041 last.

## Parallel examples

- Phase 1: T003 beside T002.
- US1: T009, T010 and T012 together.
- US2: T016 and T018 together.
- US4: T023 and T025 together.
- Polish: T033 and T034 together.

## Implementation strategy

MVP: phases 1–3, a DM through the fakes and, with the user's tokens, live. Then agreement
(US2), the safety tests (US3), the gateway's installation (US4) and failures (US5), then
the live check, which needs the user's Slack app.

## Phase 9: Convergence

- [X] T042 Align the gateway's disconnection line in `contracts/commands.md` with the code, `opscout gateway: disconnected; reconnecting`, per contracts/commands.md (contradicts)
- [X] T043 Document in research R6 that `Launchctl.unload` waits up to 15 seconds for launchd to let a job go, because `bootout` returns before a running job has stopped, per plan: research R6 (unrequested)

## Independent review (2026-11-05)

A review of the staged diff in a fresh context found no security problem and no real data,
and these, each fixed with a test first:

- A change of the chat user (or its tokens' references) was never picked up: the gateway
  reads its configuration at start, and its property list did not change. Its environment
  now holds a fingerprint of the chat setting, so install reloads it.
- A gateway retrying for hours was never reported: `last_seen` stayed fresh. `since` now
  changes only with the state, and the notice and status judge a retrying gateway by it; a
  connected one silent for 15 minutes reads `not running`.
- A second Disagree erased the reason given before; the same button again now changes
  nothing.
- A gateway stopped for good had no way back while loaded; install now offers a `restart`
  (`launchctl kickstart -k`), and status and the notice name the command.
- Two quick clicks could both read the record before either wrote; clicks of one run are
  now handled one at a time.
- An unexpected exception of a Slack call (a cut response) escaped the run without a
  record; it is now a passing fault.
- After a click, a shortened message named an empty outbox path; it names the record's.
- Connection errors were not named, and a bot token stored as the app-level token retried
  for ever; both fixed (`cannot connect (<kind>)`; `not_allowed_token_type` stops).
- A delivery whose message failed lost its outbox file in the record; it keeps it.
- The SC-004 scan passed with nothing to search when run alone; it now skips and says so.

