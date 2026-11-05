# Feature Specification: Daemon core

**Feature Branch**: `feat/007-daemon-core`

**Created**: 2026-11-05

**Status**: Implemented

**Input**: User description: "daemon-core (PLAN.md §7, Phase 1, need 4): the foundation the
daily standup and later unattended runs stand on. Delivers: (1) scheduled jobs as idempotent
`opscout run <job>` commands that record a run key for their period in the run store, so a
retry, a catch-up after sleep or a double trigger does not deliver twice (ADR-0021 rule 1);
(2) a Scheduler port with a launchd adapter that installs, uninstalls and lists the user's
jobs, idempotently (ADR-0006, ADR-0021); (3) a Runner port with ClaudeCliRunner, which starts
the user's own unmodified `claude -p` with every flag set explicitly (tool restrictions, JSON
schema, budget, max turns, no session persistence) and verifies the restricted profile from
the stream-json `system/init` event before trusting the result; one retry on a schema
failure, then `inconclusive` (ADR-0012, ADR-0018); (4) a RunStore port whose adapter writes
local run records under platformdirs, storing the CLI version used (Principle IX); (5) a
SecretStore port with a keyring adapter that resolves a secret from the name the
configuration gives, never logging its value (ADR-0021, Principle III). Each port has a fake
for tests; platform adapters are imported only by the composition root. Exit criteria:
restricted profile verified from the system/init event; idempotent install; a job triggered
twice for the same period delivers once. Must also verify whether a launchd agent can use the
user's existing Claude login (ADR-0012 open question; fallback: a `claude setup-token` token
kept in the keychain and passed only to the child). Non-goals candidates: the chat gateway
and Slack delivery (spec chat-output), the daily's content and sources (spec daily-standup),
the AgentSdkRunner, systemd/Windows adapters, any hosted component. Also decide here whether
macOS tests block merges again (PLAN.md §9)."

## Context

Phase 1 sends the daily standup on its own, 15 minutes before the meeting (need 4). Later
phases run triage with nobody at the keyboard. Both need the same machinery, and this
feature builds it once, with no job content of its own beyond what proves it works:

- **Jobs are commands** (ADR-0021). The operating system's scheduler only starts
  `opscout run <job>`; the command decides whether there is anything to do. A job delivers
  at most once per period, however many times it is started.
- **Scheduling** sits behind a port; the adapter now is launchd, the macOS user agent
  scheduler (ADR-0006).
- **Model runs** sit behind a port; the adapter now starts the user's own, unmodified
  Claude Code in headless mode with every restriction set explicitly, and checks from the
  run's own start-up report that the restrictions took effect before it trusts any output
  (ADR-0010, ADR-0012).
- **Run records** are kept locally for every run (Principle IX).
- **The harness's own secrets** are resolved by the name the configuration gives, from the
  OS keychain, and never shown (Principle III).

Two facts are still open from ADR-0012 and are settled during this feature: whether a job
started by launchd can use the user's existing Claude Code login, and, if it cannot, the
fallback of a long-lived token the user creates and keeps in the keychain.

## Clarifications

### Session 2026-11-05

- Q: Which job does this feature ship, so the scheduler and the runner have a real user and
  the login question is settled live? → A: a self-check job, `opscout run check`, that runs
  the whole path once with no tools and a small schema (FR-007).
- Q: Now that macOS-specific code exists, do the macOS tests block merges again (PLAN.md
  §9)? → A: no, they stay informational; the launchd adapter is tested everywhere through
  its seam, and a real-launchd test runs on macOS only (FR-027).
- Q: Before chat-output exists, how does the user find out that a scheduled run failed or did
  not run? → A: the plugin's existing SessionStart hook also reports it, pointing at
  `opscout daemon runs`; no new platform adapter (FR-028).
- Q: Does install, which writes and loads job files outside the repository, need an explicit
  confirmation? → A: yes, as spec 006: a yes in a terminal, or `--confirm <code>` from the
  dry run; uninstall too (FR-029).
- Q: In which time zone are schedules and periods counted? → A: the machine's local time,
  for both; the `daemon` section has no time zone (FR-001, FR-002, Edge Cases,
  Assumptions).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A scheduled job delivers once per period (Priority: P1)

The user installs their jobs once. Each job then runs at its configured time, and its
result is delivered once for its period, whether the scheduler starts it once, twice, late
after the machine wakes, or the user starts it again by hand.

**Why this priority**: it is the contract every later job relies on (ADR-0021 rule 1); a
daily sent twice, or not at all, is the failure the user would notice first.

**Independent Test**: with fake ports, start the same job twice for the same period, then
once for the next period, and count deliveries.

**Acceptance Scenarios**:

1. **Given** a job that has not delivered for the current period, **When** it is started,
   **Then** it runs, delivers once, and its run record holds the period's run key and the
   outcome `delivered`.
2. **Given** a job that has already delivered for the current period, **When** it is started
   again (by the scheduler or by hand), **Then** it does not run the model, does not deliver,
   and records the start as `skipped` with the run key it found.
3. **Given** two starts of the same job for the same period at the same moment, **When** both
   run, **Then** exactly one delivers and the other records `skipped`.
4. **Given** a run that failed or ended `inconclusive` for the period, **When** the job is
   started again in the same period, **Then** it runs again; delivery still happens at most
   once.
5. **Given** the user passes `--force`, **When** the job has already delivered for the
   period, **Then** it runs and delivers again, and the record says it was forced.
6. **Given** the machine was asleep at the scheduled time, **When** it wakes and the
   scheduler starts the missed job, **Then** the job runs for the current period.

---

### User Story 2 - Jobs are installed, listed and removed safely (Priority: P1)

The user installs the configured jobs into the operating system's scheduler with one
command, sees what is installed, and removes it all with another. Running install again
changes nothing unless the configuration changed.

**Why this priority**: without it nothing runs on its own; an install that duplicates or
leaves stale jobs behind is hard for the user to notice and undo.

**Independent Test**: with a fake scheduler, and with the launchd adapter against a
temporary agents directory and a fake service manager: install, install again, change the
configuration, install, uninstall; check the files and the calls each time.

**Acceptance Scenarios**:

1. **Given** jobs in the configuration and none installed, **When** the user runs install
   and confirms, **Then** each enabled job is installed with its schedule and the command
   shows what it added.
2. **Given** the jobs are installed and the configuration is unchanged, **When** the user runs
   install again, **Then** nothing is written or reloaded, and the user is told so.
3. **Given** a job's schedule changed, or a job was removed or disabled in the configuration,
   **When** the user runs install, **Then** only that job is updated or removed, and jobs
   that were not installed by opscout are never touched.
4. **Given** `--dry-run`, **When** the user runs install, **Then** the changes and a
   confirmation code are listed and nothing is written.
5. **Given** installed jobs, **When** the user runs status, **Then** each job is listed with
   its schedule, whether it is loaded, and its last outcome and time from the run records.
6. **Given** installed jobs, **When** the user runs uninstall and confirms, **Then** every
   job opscout installed is unloaded and removed, and running uninstall again changes
   nothing.
7. **Given** the engine the jobs were installed with no longer exists at its recorded path
   (for example after a plugin update), **When** the user runs status, **Then** it says so
   and tells the user to run install again.
8. **Given** pending changes, **When** install or uninstall runs without a yes in a terminal
   and without the confirmation code of the current changes, **Then** nothing is written or
   loaded, and the changes and the code are printed; a code is refused once the
   configuration or the installed jobs have changed since it was printed.

---

### User Story 3 - Model runs are restricted, and the restriction is checked (Priority: P1)

A job that needs the model gets a headless Claude Code run with exactly the tools, budget,
turn limit and output schema the job declares. The engine reads the run's start-up report
and refuses the result if the run started with anything more than it asked for.

**Why this priority**: unattended runs read untrusted input; a restriction that silently did
not apply is the worst failure of this phase (Principle II, ADR-0010).

**Independent Test**: with recorded start-up reports and outputs, run the runner against a
fake Claude Code executable that prints them; check the flags it was given, the verdict on
each report, and the outcome.

**Acceptance Scenarios**:

1. **Given** a job's run profile (allowed tools, output schema, budget, turn limit, model),
   **When** the runner starts Claude Code, **Then** every restriction is passed explicitly,
   session persistence is off, and nothing is left to Claude Code's defaults.
2. **Given** a start-up report whose tools, tool servers or permission mode differ from the
   profile, **When** the runner reads it, **Then** it stops the run, discards any output, and
   records the outcome `refused` with the differences.
3. **Given** an output that fails the job's schema, **When** the run ends, **Then** the runner
   starts one more run whose prompt carries the validator's message.
4. **Given** the second output also fails, **When** it ends, **Then** the outcome is
   `inconclusive` and the user is told, not silently dropped.
5. **Given** a run that exceeds its budget or turn limit, or Claude Code exits with an error,
   **When** the run ends, **Then** the outcome is `failed` with the reason, and no output is
   delivered.
6. **Given** a run whose output is valid, **When** it ends, **Then** the record holds the
   Claude Code version, model, cost, duration and turns from the run's own report.
7. **Given** the scheduler's minimal environment, **When** the runner starts Claude Code,
   **Then** the child gets only the environment variables it needs, and Claude Code is found
   from the configuration or the search path, or the run fails saying where it looked.

---

### User Story 4 - The harness's own secrets stay in the keychain (Priority: P2)

When a job needs a credential of the harness itself (the first is the fallback Claude token,
if a scheduled job cannot use the user's login), the user stores it once in the OS keychain
under the name the configuration gives, and the engine passes it only to the process that
needs it.

**Why this priority**: it is needed only if the login check fails, and by chat-output next;
but a token in a file or a log is an incident (Principle III).

**Independent Test**: with a fake secret store and with the keyring adapter on an in-memory
backend: store, check, resolve and pass a secret; search every output, log and record for
its value.

**Acceptance Scenarios**:

1. **Given** a secret name in the configuration, **When** the user runs the store command,
   **Then** the value is read without echo and stored in the keychain under that name.
2. **Given** a stored secret, **When** the user runs the check command, **Then** it reports
   that it exists and where, and never its value.
3. **Given** a missing secret that a job needs, **When** the job runs, **Then** it fails
   before starting Claude Code, naming the secret and the command to store it.
4. **Given** a resolved secret, **When** the runner starts Claude Code, **Then** the value
   reaches only that child's environment, and no output, log or run record contains it.

---

### User Story 5 - Every run leaves a record (Priority: P2)

Every start of a job, including skipped and refused ones, leaves a local record the user
and later features (chat-output's agreement buttons, run-insights) can read.

**Why this priority**: Principle IX; and the run key that makes jobs idempotent lives in
these records.

**Independent Test**: run each outcome through a job with fake ports and a temporary run
store; read the records back.

**Acceptance Scenarios**:

1. **Given** any start of a job that begins (FR-006), **When** it ends, **Then** one record
   is written with the
   trigger (scheduler or user), job, engine version, run key, outcome, start and end times,
   and, when the model ran, the Claude Code version, model, tools called, cost and turns.
2. **Given** a record, **When** it is written, **Then** it holds inputs by reference, an
   empty agreement field for chat-output to fill, and no secret value.
3. **Given** a write that fails half-way, **When** the records are read, **Then** each record
   is either complete or absent.
4. **Given** the records, **When** the user lists the recent runs of a job, **Then** they see
   them newest first with outcome and time.
5. **Given** a job whose last run was `refused`, `inconclusive` or `failed`, or that has no
   run for its most recent scheduled period, **When** the user starts a Claude Code session,
   **Then** the session start says so and names the command to see the runs; when every job
   is fine, it says nothing about jobs.

---

### Edge Cases

- **No jobs in the configuration.** Install installs nothing and removes what opscout had
  installed; status says there is nothing configured.
- **An invalid configuration.** Install, run and status stop and point to
  `opscout config validate`; install changes nothing.
- **Unknown job name** in `opscout run`: exit with the list of configured jobs.
- **The period boundary.** The period is computed once at start, in the machine's local
  time; a run that crosses midnight belongs to the period it started in.
- **Clock or time zone changes** between two starts (travel, daylight saving time): the run
  key, not the wall clock, decides whether the period already delivered; the schedule follows
  the machine's new local time with no reinstall.
- **The machine was off for days.** The scheduler starts the job once on wake; it runs for the
  current period only, never for the missed ones.
- **A stale lock** left by a run that crashed: a later start takes it over once its owner is
  gone, and the record of the crashed run, if any, stays as it was.
- **Claude Code not installed or not logged in**: the run fails before any output, and says
  which.
- **Claude Code older than the version the runner was tested with**: the start-up report
  check refuses the run (FR-015), and the record names both versions.
- **The start-up report never arrives** (Claude Code changed its event format): the run is
  `refused`, never trusted by default.
- **A job file written by hand** in the agents directory under opscout's prefix: install
  treats it as opscout's and replaces it; anything without the prefix is never read or
  changed.
- **The keychain is locked** or unavailable: the secret is reported as unavailable, not as
  missing, and the job fails without starting Claude Code.
- **An operating system with no scheduler adapter** (anything but macOS in this feature):
  `opscout run` works; `daemon install`, `uninstall` and `status` stop with exit 2 and say
  that no scheduler is available for this system; the session notice never reports a job
  as not installed there.
- **The run store directory is missing**: it is created; if it cannot be written, the job
  does not run, since it could not prove it delivers once.

## Requirements *(mandatory)*

### Functional Requirements

#### Configuration

- **FR-001**: The configuration MUST accept an optional `daemon` section, added to schema
  version 1 as an additive change (spec 002), holding: the jobs (by name, each with an
  enabled flag, a schedule of time of day and weekdays, and run limits that override the
  job's defaults: budget, turn limit, model), an optional path to the Claude Code
  executable, and optional secret references (keychain service and
  account, as spec 002's keychain reference already defines).
- **FR-002**: Validation MUST refuse a job name the engine does not know, a secret name the
  engine does not use, an impossible time or weekday, and a non-positive budget or turn
  limit.

#### Jobs

- **FR-003**: `opscout run <job>` MUST compute the job's period at start and its run key from
  the job and the period, and MUST NOT run the model or deliver when a record of the same
  key has the outcome `delivered`, unless `--force` is given.
- **FR-004**: Two starts of the same key MUST NOT both deliver: a start MUST hold an
  exclusive lock on the key from the check to the record of its outcome, and a start that
  cannot take the lock MUST record `skipped`.
- **FR-005**: A job MUST deliver through an output port; delivery happens only after a valid
  output, and the outcome `delivered` is recorded only after delivery succeeds.
- **FR-006**: Every start that begins MUST end with exactly one of the outcomes `delivered`,
  `skipped`, `refused`, `inconclusive` or `failed`, and an exit status that distinguishes
  success (`delivered`, `skipped`) from the rest. A start that cannot begin (an invalid
  configuration, an unknown job, a run store that cannot be written) writes no record and
  exits with a third status, naming the reason.
- **FR-007**: The engine MUST ship one job, `check`, that runs the whole path once: a model
  run with no tools and a small output schema, the start-up report check, the run record and
  a delivery through the output port. Its period is the calendar day. It is the scheduler's
  and the runner's first user (Principle VIII), settles the login question live (FR-019),
  and doubles as the user's diagnostic.
- **FR-008**: The output port's only adapter in this feature MUST write each delivery to a
  local outbox file under the user's data directory; chat-output adds the direct message.

#### Scheduler

- **FR-009**: `opscout daemon install` MUST make the installed jobs match the enabled jobs of
  the configuration: add, update or remove only jobs under opscout's own label prefix, and
  write or reload nothing that is already up to date. `--dry-run` MUST list the changes and
  a confirmation code derived from the current and the new state, and write nothing.
- **FR-010**: An installed job MUST start the same engine that installed it, by absolute
  path, with the configuration directory it was installed with, and send its output and
  errors to a log file under the user's log directory.
- **FR-029**: Install and uninstall MUST change anything only after a yes in a terminal, or
  with `--confirm <code>` matching the current changes, as spec 006's apply does; otherwise
  they MUST change nothing and print the changes and the code.
- **FR-011**: `opscout daemon uninstall` MUST unload and remove every job under opscout's
  label prefix, and nothing else.
- **FR-012**: `opscout daemon status` MUST list each configured and each installed job with
  its schedule, whether it is loaded, its last outcome and time, and any mismatch between
  the two (not installed, stale, engine path missing).
- **FR-013**: The scheduler MUST be a port with a fake; the launchd adapter MUST reach the
  service manager through a seam that tests replace, so it is tested on every operating
  system.

#### Runner

- **FR-014**: The runner MUST be a port. Its Claude Code adapter MUST start the user's own
  executable in headless mode with, explicitly: the allowed tools (none unless the job
  declares some), no tool servers but those the job declares, a non-interactive permission
  mode, the output schema, the budget, the turn limit, the model, no session persistence,
  and machine-readable streaming output.
- **FR-015**: The runner MUST read the run's start-up report and compare its tools, tool
  servers, permission mode and model with the profile; on any difference, or when no report
  arrives, it MUST stop the run and record `refused` with the differences.
- **FR-016**: The runner MUST validate the output against the job's schema; on failure it
  MUST start one more run carrying the validator's message, and after a second failure end
  as `inconclusive` (ADR-0018). An `inconclusive` or `refused` outcome MUST reach the user
  through the output port as a notice, not as a result.
- **FR-017**: The runner MUST pass the child only an allow-listed environment (what Claude
  Code needs to find its login and the user's home, plus the secrets the job declares), and
  MUST find the executable from the configuration, else the search path, else fail naming
  where it looked.
- **FR-018**: The runner MUST record the Claude Code version, model, cost, duration, turns
  and tools called from the run's own reports.
- **FR-019**: The feature MUST establish, on the maintainer's machine, whether a job started
  by launchd can use the user's existing Claude Code login, and record the result in the
  spec. If it cannot, the runner MUST pass a token from the secret store to the child
  only, and the quickstart MUST say how to create and store it.

#### Run store

- **FR-020**: The run store MUST be a port with a fake; its adapter MUST write one record per
  start under the user's data directory, in one step, and read them back by job and by run
  key.
- **FR-021**: A record MUST hold the trigger, job, engine version, run key, period, outcome,
  reason, start and end times, inputs by reference, an empty agreement field, and the
  runner's facts (FR-018) when the model ran; it MUST NOT hold a secret value.
- **FR-022**: `opscout daemon runs [<job>]` MUST list recent records newest first.
- **FR-028**: The plugin's SessionStart hook MUST also report, for each enabled job, a last
  outcome of `refused`, `inconclusive` or `failed`, or a missing run for its most recent
  scheduled period, with the command to see the runs. It reads only the configuration and
  the run records, keeps no state of its own (the notice repeats until a later run
  succeeds), says nothing when all is well or no job is configured, and keeps the hook
  within its time limit (spec 005).

#### Secret store

- **FR-023**: The secret store MUST be a port with a fake; its adapter MUST resolve a secret
  from the keychain reference the configuration gives, and tell a missing secret from an
  unavailable keychain.
- **FR-024**: `opscout secret set <name>` MUST read the value without echo and store it;
  `opscout secret check [<name>]` MUST report existence and location only. No command,
  log, error or record may contain a secret's value.

#### Architecture and proof

- **FR-025**: The launchd and keychain adapters MUST be imported only by the composition
  root, enforced by an import contract (ADR-0021).
- **FR-026**: Tests MUST cover each acceptance scenario and edge case, including a job
  started twice for the same period delivering once, an idempotent install, and refused
  runs for each kind of start-up report difference. The runner's flags and the report
  fields it reads MUST be pinned by contract tests against recorded reports of the CLI
  version checked (ADR-0012).
- **FR-027**: The CI policy for macOS MUST be decided in this feature and recorded in
  ADR-0016 and PLAN.md §9: the macOS test jobs stay informational. The launchd adapter is
  tested on every operating system through its seam (FR-013); a test against the real
  service manager runs only on macOS, locally, on every pull request and daily on `main`.

### Key Entities

- **Job**: a named, engine-defined procedure with its period rule, run profile and output;
  enabled and scheduled by the configuration.
- **Period and run key**: the span a job delivers once in (for example a calendar day in the
  machine's local time) and the key derived from job and period.
- **Run profile**: what a model run may use: tools, tool servers, permission mode, model,
  output schema, budget, turn limit, secrets.
- **Start-up report**: what Claude Code says it started with; compared with the profile.
- **Run record**: one per start; outcome, facts, references; the agreement field.
- **Installed job**: the scheduler's entry for a job, under opscout's label prefix.
- **Secret reference**: a keychain service and account named by the configuration.

## Non-Goals

- **Never deliver twice for one period without `--force`, never trust a run whose start-up
  report was not checked, never write a secret's value anywhere, and never touch a
  scheduler entry outside opscout's prefix.**
- **Chat.** The gateway, Slack, direct messages and agreement buttons are chat-output; this
  feature leaves the agreement field empty.
- **The daily's content.** Its sources, prompt, schedule default and Monday rule are
  daily-standup.
- **Tools for unattended runs.** No MCP server or investigation tools here; profiles allow no
  tools unless a job declares them, and no job here declares any.
- **Other runners and schedulers.** No Agent SDK runner, no systemd or Task Scheduler
  adapter, no hosted component (ADR-0006, ADR-0021).
- **Catching up missed periods.** A job runs for the current period only.
- **Retention and rotation** of run records and logs.
- **Storing or proxying the user's Claude login.** The runner uses whatever login Claude Code
  has; the fallback token is the user's own, created by them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across the test set, a job started any number of times for one period delivers
  exactly once (and once more per `--force`).
- **SC-002**: Installing the same configuration twice writes and reloads nothing the second
  time.
- **SC-003**: 100 % of the recorded start-up reports that differ from their profile end as
  `refused`, and none of their output is delivered.
- **SC-004**: A secret's value appears in 0 outputs, logs and run records across the test
  set.
- **SC-005**: On the maintainer's machine, a job installed by `opscout daemon install` runs at
  its scheduled time with no one at the keyboard and leaves a delivered outbox entry and a
  run record; the login result is recorded in this spec.
- **SC-006**: A skipped start (already delivered) finishes in under one second, since it
  never starts the model.
- **SC-007**: 100 % of the functional requirements are covered by a test.

## Assumptions

- **launchd user agents** run a missed calendar job once when the machine wakes, and run in
  the user's session, where the login keychain is normally unlocked; checked during the
  plan. **Login result (FR-019, SC-005), 2026-11-05**: a job installed by `opscout daemon
  install` ran at its minute and delivered with `apiKeySource: none`, so a launchd job uses
  the user's existing Claude Code login; observed with the session unlocked, not with the
  screen locked. The `claude_token` fallback stays, built and tested.
- **Claude Code's headless mode** reports what it started with in its first streamed event,
  including tools, tool servers, permission mode, model and version, and reports cost,
  turns and duration at the end; pinned in the plan against CLI 2.1.318 (PLAN.md §8).
- **One machine.** The run store and locks are local; two machines with the same
  configuration would each deliver.
- **Times** are wall-clock times in the machine's local time, for schedules and periods
  alike, as launchd schedules them; no time zone is configured for jobs.
- **No eval suite**: no skill or agent behavior is added; the proof is tests and the live
  check of SC-005 (ADR-0013 covers skills).
- **Two runtime dependencies** arrive as ADR-0021 justifies: `platformdirs` and `keyring`.

## Actuals

- **Effort**: one session on 2026-11-05, from specify to the pull request.
- **Live checks (quickstart, 2026-11-05)**: `opscout run check` delivered, skipped the
  second start and delivered again with `--force` (under 0.001 USD each); install printed
  the change and a code, applied it with the code, and then found nothing to change; the
  installed job ran at 16:05 local time and delivered; a failed run appeared in the
  SessionStart output through the plugin's launcher; uninstall removed the job and a
  second uninstall changed nothing.
