# Feature Specification: Chat output

**Feature Branch**: `feat/008-chat-output`

**Created**: 2026-11-05

**Status**: Implemented

**Input**: User description: "chat-output (PLAN.md §7, Phase 1, need 4): the second piece the
daily standup stands on. Delivers: (1) a Slack app manifest in deploy/ that the user installs
in their own workspace, with the fewest scopes needed for DMs to the user and interactive
buttons (no channel reading, no public HTTP endpoint); (2) a chat gateway in Socket Mode
(connects outward over a WebSocket, ADR-0021), the engine's first long-running process,
installed and supervised as a launchd job by `opscout daemon install` like the scheduled
jobs; (3) a Delivery adapter that sends a job's result or notice as a DM to the one
configured user only, next to the local outbox, so a delivery is recorded only after Slack
accepted it (spec 007, FR-005); (4) agreement buttons (agree / disagree, optionally a short
reason) on each delivered message, whose click is stored in the run record's existing
`agreement` field (spec 007, Principle IX), idempotently; (5) the bot token and the
app-level token kept in the OS keychain through the existing SecretStore (new known secret
names), never logged. The `check` job is the first user. Exit criteria: a DM delivered from a
scheduled run; an agreement click stored in the run log. Constraints: DMs only, to the
configured user only; messages from anyone else, and events other than the user's button
clicks, are ignored; untrusted input never reaches a model in this feature; nothing leaves
the machine except the DM to the user. Non-goals candidates: mentions and thread replies
(thread-bot, Phase 2), reading channels or alert bots, the daily's content (daily-standup),
team-wide delivery, hosted components, other chat platforms. Also in this pull request:
PLAN.md's status line says spec 007 is merged, and §9 records that the spec-004 push-guard
timing test (1 s) failed once on a hosted macOS runner under coverage (1.09 s)."

## Context

Spec 007 built scheduled jobs that deliver to a local outbox file and leave an empty
agreement field in each run record. The daily standup (need 4) must instead arrive where the
user already looks, a direct message in the team's chat, 15 minutes before the meeting; and
Phase 3 can only begin once the run log shows how often the user agreed with what the
harness sent (Principle IX, PLAN.md §7). This feature closes both gaps for every job:

- **Delivery by direct message.** When chat is configured, a job's result or notice goes to
  the user as a direct message, besides the outbox copy, and counts as delivered only once
  the chat service accepted it.
- **Agreement.** Each delivered result carries two buttons, agree and disagree, with an
  optional short reason; the click is stored in that run's record.
- **A gateway.** Receiving clicks needs a process that stays connected to the chat service.
  It connects outward, so the machine opens no port and needs no public address
  (ADR-0021), and it is installed and removed with the scheduled jobs.
- **Least access.** The chat app the user installs can write direct messages to its user
  and receive that user's button clicks, nothing else: it reads no channel and no message.

The chat service is Slack; it sits behind a port, so another service would be another
adapter. This pull request also brings PLAN.md up to date: spec 007 is merged, and one open
item records that the spec-004 push-guard timing test failed once on a hosted macOS runner
under coverage.

## Clarifications

### Session 2026-11-05

- Q: When a direct message cannot be sent, what happens to the run? → A: the same run
  retries for up to 10 minutes, with growing waits, then ends `failed`; the outbox copy is
  written either way (FR-007).
- Q: How long does the gateway run? → A: all the time while the user is logged in, kept
  running by the service manager (FR-012).
- Q: When a run ends `failed` but the chat service works, does the user get a direct
  message? → A: yes, a short failure notice without agreement buttons; the outcome stays
  `failed` (FR-024).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A job's result arrives as a direct message (Priority: P1)

When a scheduled or manual run delivers, the user gets the result as a direct message from
the opscout app, readable as written, and the run is recorded as delivered only after the
chat service accepted the message.

**Why this priority**: it is the point of the feature and the daily's delivery channel; the
outbox file alone is not where the user looks.

**Independent Test**: with a fake chat port, run a job and check the message sent, its
recipient and the record; once on the maintainer's workspace, run the `check` job from the
scheduler and see the message arrive.

**Acceptance Scenarios**:

1. **Given** chat is configured and its tokens are stored, **When** a job delivers, **Then**
   the user receives one direct message with the job's text, the outbox copy is written as
   before, and the record holds both references and the outcome `delivered`.
2. **Given** a result whose text uses headings, lists, emphasis and code, **When** it is
   sent, **Then** the message shows them in the chat's own formatting, and nothing of the
   text is lost or reordered.
3. **Given** a result longer than one chat message can hold, **When** it is sent, **Then**
   the message holds as much as fits, says it was shortened, and names the outbox file
   with the full text.
4. **Given** the run ends `refused` or `inconclusive`, **When** its notice is delivered,
   **Then** the user receives the notice as a direct message, without agreement buttons.
5. **Given** chat is not configured, **When** a job delivers, **Then** it behaves exactly as
   spec 007 specifies: outbox only.
6. **Given** the chat service refuses or cannot be reached, **When** a job delivers,
   **Then** the run keeps trying to send the message for up to 10 minutes; if it is
   accepted, the run is `delivered`; if not, the run is `failed`, and the next session
   start says so.

---

### User Story 2 - The user records agreement from the message (Priority: P1)

Below each delivered result the user finds "agree" and "disagree". A click is stored in the
run's record, the message changes to show the choice, and the user may add a short reason.

**Why this priority**: the agreement rate is the evidence Phase 3 depends on (PLAN.md §7);
without it the run log cannot judge any job.

**Independent Test**: with a fake chat port, feed the gateway button clicks and dialog
submissions and check the records and the message updates.

**Acceptance Scenarios**:

1. **Given** a delivered result, **When** the user clicks "agree", **Then** the run's
   record holds `agree`, the time and no reason, and the message shows the choice.
2. **Given** a delivered result, **When** the user clicks "disagree", **Then** a short
   dialog offers an optional reason; on submit the record holds `disagree`, the time and
   the reason, if any; on cancel it holds `disagree` without a reason.
3. **Given** a recorded choice, **When** the user clicks the other button, **Then** the
   newer choice replaces the older one and the message shows it.
4. **Given** a recorded choice, **When** the same click arrives again (a double click, or a
   retry from the chat service), **Then** the record does not change.
5. **Given** a message whose run record no longer exists or cannot be read, **When** the
   user clicks, **Then** nothing is stored and the message says the choice could not be
   recorded.
6. **Given** the gateway is not running when the user clicks, **When** it starts again,
   **Then** the user can click again and the click is stored; a click while it was down is
   not stored silently as something else.

---

### User Story 3 - Only the user, only direct messages (Priority: P1)

The app writes only to its one configured user, and the gateway acts only on that user's
clicks on messages the app sent. Everything else is ignored, and nothing the chat service
sends reaches a model.

**Why this priority**: chat content is untrusted input (ADR-0010); a delivery to the wrong
person is a leak; and an agreement recorded from someone else would corrupt the evidence.

**Independent Test**: with a fake chat port, deliver and send the gateway clicks from
another user, events of other kinds, and clicks on messages the app did not send; check
that nothing is sent elsewhere and nothing is stored.

**Acceptance Scenarios**:

1. **Given** any delivery, **When** it is sent, **Then** its only recipient is the
   configured user, as a direct message; never a channel, a group or another person.
2. **Given** a click from anyone but the configured user, **When** the gateway receives it,
   **Then** nothing is stored and nothing is answered.
3. **Given** an event that is not a click on one of the app's agreement buttons or its
   reason dialog, **When** the gateway receives it, **Then** it is acknowledged and
   otherwise ignored, and its content is not written anywhere.
4. **Given** the app's manifest, **When** it is checked, **Then** it asks only for the
   permissions needed to write direct messages to its user, to update its own messages and
   to open the reason dialog, and it subscribes to no message or channel events.
5. **Given** a reason the user typed, **When** it is stored, **Then** it is kept as plain
   text in the record only, never logged, and never sent to a model by this feature.

---

### User Story 4 - The user sets up chat once (Priority: P2)

The user creates the app in their workspace from the shipped manifest, stores its two
tokens in the keychain, names themself in the configuration, and installs the gateway with
the scheduled jobs; status shows whether it all works.

**Why this priority**: needed once per machine, after which stories 1 and 2 work unattended.

**Independent Test**: with fakes and a temporary agents directory: configure chat, install
twice, check the gateway job appears once and is not reinstalled; remove chat from the
configuration and install again; check the gateway is removed.

**Acceptance Scenarios**:

1. **Given** the manifest and the reference documentation, **When** the user follows the
   setup steps, **Then** they create the app, install it in their workspace and get the two
   tokens without writing any value into a file.
2. **Given** the two token names, **When** the user stores each with the existing secret
   command, **Then** the check command reports both present, with location only.
3. **Given** chat configured, **When** the user runs install and confirms, **Then** the
   gateway is installed beside the scheduled jobs, started, and kept running; a second
   install changes nothing.
4. **Given** chat removed from the configuration, **When** the user runs install and
   confirms, **Then** the gateway is removed; uninstall removes it too.
5. **Given** chat configured, **When** the user runs status, **Then** it shows whether the
   gateway is installed and running, and when it last connected.

---

### User Story 5 - Chat failures are visible (Priority: P2)

When a direct message cannot be sent, a token is missing or revoked, or the gateway is not
running, the user finds out at the next session start or from status, with the command that
helps.

**Why this priority**: an unattended delivery that silently fails is worse than none; the
user would wait for a daily that never comes.

**Independent Test**: with fakes, make the chat port refuse, remove a token, and stop the
gateway; check the records, status and the session-start notice.

**Acceptance Scenarios**:

1. **Given** a missing chat token, **When** a job delivers, **Then** the run is `failed`
   before any model run, naming the token and the command to store it.
2. **Given** chat configured and working, **When** a run ends `failed` for another reason
   (Claude Code failed, a secret is missing, the run took too long), **Then** the user
   receives a short direct message naming the job, the period, the reason and the command
   to see the runs, without agreement buttons, and the outcome stays `failed`.
3. **Given** a token the chat service rejects (revoked, app removed), **When** a job
   delivers or the gateway connects, **Then** the run is `failed`, or the gateway stops
   retrying, and both say the token was rejected; the token's value is never shown.
4. **Given** chat configured and the gateway not installed or not running, **When** the
   user starts a Claude Code session, **Then** the session start says so, with the command
   to fix it.
5. **Given** the network drops, **When** it returns, **Then** the gateway connects again on
   its own, without the user doing anything.

---

### Edge Cases

- **The user deletes the direct message** before clicking: nothing happens; the run keeps
  an empty agreement.
- **A click days later**: it is stored like any other, with its own time; there is no
  deadline.
- **The configured user changes** in the configuration: later deliveries go to the new
  user; clicks are accepted only from the user configured when the click arrives.
- **Two clicks at nearly the same moment**: the record ends with exactly one of them, never
  a mix, and never a corrupted file.
- **A delivery and a click on the same run at once** (a forced rerun of the period while
  the user clicks an older message): each click updates only the record of the run whose
  message was clicked.
- **The chat service limits the app's rate**: the send waits as the service asks, within
  the delivery's 10 minutes.
- **The gateway runs twice** (installed and started by hand): at most one copy stays
  connected; a second start says one is already running and exits.
- **The machine sleeps** for hours: the gateway reconnects on wake; clicks made while it
  slept were refused by the chat service and can be made again.
- **An invalid configuration** when the gateway starts or restarts: it does not connect,
  says why in its log, and status shows it.
- **The chat section is present but the scheduler is unavailable** (not macOS): delivery by
  direct message still works for manual runs; installing the gateway says no scheduler is
  available, as spec 007 does for jobs.

## Requirements *(mandatory)*

### Functional Requirements

#### Configuration

- **FR-001**: The configuration MUST accept an optional chat setting under the `daemon`
  section, additive to schema version 1, holding the chat service (only Slack), the
  configured user's chat ID, and nothing secret; validation MUST refuse a malformed ID.
- **FR-002**: The known secret names MUST gain the chat's bot token and app-level token,
  stored and checked with the existing secret commands; a chat setting without both
  configured MUST fail validation, naming the missing one.
- **FR-003**: Without the chat setting, delivery, records and the commands MUST behave
  exactly as spec 007 specifies.

#### The app

- **FR-004**: The repository MUST ship the chat app's manifest, which asks only for the
  permissions to write direct messages to its user, to update its own messages and to open
  a dialog, enables connection by outward socket, and subscribes to no message, channel or
  mention event; a test MUST hold its permission list to that set.
- **FR-005**: The reference documentation MUST give the setup: create the app from the
  manifest, install it, create the app-level token, store both tokens, configure the user,
  install.

#### Delivery

- **FR-006**: When chat is configured, a delivery MUST write the outbox copy first, then
  send one direct message to the configured user, and record `delivered` only after the
  chat service accepted the message; the record MUST keep the outbox file and a reference
  to the message.
- **FR-007**: A delivery the chat service cannot receive (no network, the service down or
  limiting the rate) MUST be retried by the same run, with growing waits, for up to 10
  minutes in all; a delivery still not accepted, or one the service refuses for good (a
  rejected token, an unknown user), MUST end the run as `failed` with the reason, never
  `delivered`.
- **FR-008**: The message MUST render the job's text in the chat's formatting (headings,
  lists, emphasis, code, links) without loss or reordering; a text too long for one message
  MUST be cut at a line boundary, say so, and name the outbox file.
- **FR-009**: A result MUST carry the two agreement buttons; a notice MUST NOT.
- **FR-010**: The only recipient MUST be the configured user, as a direct message; the
  delivery MUST never address a channel, group or other person, whatever the job's text.
- **FR-011**: The chat tokens MUST be resolved only by the processes that talk to the chat
  service, and MUST NOT reach a model run's environment, a log, a record or any output.

#### The gateway

- **FR-012**: The gateway MUST be a command that connects outward to the chat service and
  stays connected for as long as the user is logged in, reconnecting by itself after a
  network loss, a sleep or a service restart; the service manager MUST start it again if it
  ends.
- **FR-013**: `opscout daemon install` MUST install the gateway as one more scheduled-jobs
  entry under opscout's prefix when chat is configured, kept running by the service manager,
  and remove it when chat is not; the same confirmation, idempotency and uninstall rules as
  spec 007 apply.
- **FR-014**: The gateway MUST act only on clicks of the app's agreement buttons and
  submissions of its reason dialog, by the configured user, on messages that carry a run id
  it can find; every other event MUST be acknowledged and ignored without storing its
  content.
- **FR-015**: A valid click MUST set the run record's agreement to the choice, the time and
  the optional reason, replacing an earlier choice, writing the record in one step; the same
  choice arriving again MUST leave the record unchanged; the message MUST then show the
  choice.
- **FR-016**: A reason MUST be optional, one paragraph of at most 500 characters, stored as
  plain text in the record only, never logged and never given to a model by this feature.
- **FR-017**: A click whose run record is missing or unreadable MUST store nothing and tell
  the user, in the message, that the choice could not be recorded.
- **FR-018**: Only one gateway MUST be connected at a time on a machine; a second start MUST
  say so and exit.
- **FR-019**: The gateway's log MUST hold connection states, counts of handled and ignored
  events, and errors by kind; never a token, a message text or a reason.

#### Visibility

- **FR-020**: `opscout daemon status` MUST show, when chat is configured, whether the
  gateway is installed and loaded, and when it last connected.
- **FR-021**: The SessionStart notice (spec 007, FR-028) MUST also report, when chat is
  configured, a gateway not installed or not connected for more than 15 minutes, with the
  command to fix it.

- **FR-024**: When chat is configured, a run that ends `failed` for a reason other than its
  own chat delivery MUST send a short notice as a direct message (job, period, reason, the
  command to see the runs), without agreement buttons, under the same retry rule as
  FR-007; the outcome MUST stay `failed`, so a later start of the period still runs.

#### Architecture and proof

- **FR-022**: The chat service MUST sit behind a port with a fake; its adapter MUST be built
  only by the composition root (spec 007, FR-025), and no test MUST contact the chat
  service.
- **FR-023**: Tests MUST cover each acceptance scenario and edge case, including clicks from
  another user, foreign events, repeated clicks, and a token that never appears in any
  output; and the exit criteria MUST be shown live on the maintainer's workspace: a direct
  message delivered from a scheduled run, and a click stored in its record.

### Key Entities

- **Chat setting**: the chat service and the configured user's chat ID; part of the
  `daemon` section.
- **Chat delivery**: a direct message sent for one run: the run id, the message reference,
  whether it carries agreement buttons.
- **Agreement**: on a run record, the choice (`agree` or `disagree`), its time and an
  optional reason; empty until the user clicks.
- **Gateway**: the long-running process that holds the outward connection and handles
  clicks; installed and supervised like a job, with its last connection time.

## Non-Goals

- **Never write to anyone but the configured user, never read a channel or a message,
  never act on another person's click, never put a token or a reason in a log, and never
  give chat content to a model.**
- **Mentions and thread replies** (thread-bot, Phase 2), reading alert channels or other
  bots' messages, and any reply in a thread.
- **The daily's content and schedule** (daily-standup).
- **Team-wide delivery**: more than one recipient, channels, or group messages.
- **Other chat services** and any hosted component: the gateway runs on the user's machine.
- **Acting on a click** beyond storing it: no rerun, no ticket, no follow-up message.
- **Reports on agreement**: rates and exports are run-insights.
- **Retention** of run records, outbox files and logs (an open item in PLAN.md §9).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A scheduled run's direct message reaches the user within one minute of the
  run's end while the machine is online; shown live on the maintainer's workspace.
- **SC-002**: While the gateway is connected, a click is stored in the run record within
  five seconds, and the message shows the choice.
- **SC-003**: Of clicks and events not from the configured user on the app's own buttons,
  none is stored or answered; of the configured user's clicks while connected, all are.
- **SC-004**: A sentinel token value and a sentinel reason appear in no log, output or
  model environment across the whole test suite; the reason appears only in its record.
- **SC-005**: A second `opscout daemon install` with unchanged configuration changes
  nothing, gateway included.
- **SC-006**: After the network returns, the gateway is connected again within one minute,
  with no action from the user.
- **SC-007**: When the chat service cannot be reached, no run is recorded as `delivered`
  and the next session start says so.

## Assumptions

- **Slack** is the chat service, and the user can create and install an app in their own
  workspace without an administrator (recorded in the private configuration).
- **Socket Mode** delivers interactive events over an outward connection that the chat
  service authenticates, so the gateway needs no public address and no request signing.
- **One machine, one user, one gateway**, as in spec 007.
- **Delivery reuses spec 007's run store, lock and outcomes**; this feature adds a delivery
  adapter and writes the existing agreement field, without a new record version.
- **The `check` job is the first user**; the daily standup is the next.
- **A runtime dependency for the chat service** may be added, with its reason in the plan.

## Actuals

- **Effort**: one session on 2026-11-05, from specify to the pull request.
- **Live checks (quickstart, 2026-11-05, the maintainer's workspace)**:
  - A manual `opscout run check` delivered by direct message, after a fix found here:
    python.org's Python on macOS could not verify Slack's certificate, and the run retried
    for 10 minutes; Slack's clients now trust the operating system's certificates, and an
    unverifiable certificate is a refusal (research R1).
  - `daemon install` added `opscout.check` and `opscout.gateway`; a second install changed
    nothing; the gateway connected at once.
  - The scheduled `check` ran from launchd and delivered by direct message (SC-001).
  - Agree, then Disagree, then a reason in the dialog: each was stored in that run's
    record within a second, the message showed each choice, and the reason appeared in no
    log (SC-002, exit criterion).
  - Wi-Fi off and on: the gateway logged the disconnection and was connected again within
    seconds, with nothing done by hand (SC-006).
  - Uninstall removed both entries; `launchctl bootout` returned before the gateway had
    stopped, so `Launchctl.unload` now waits until launchd lets the job go (found here,
    fixed with a test, checked again live).

