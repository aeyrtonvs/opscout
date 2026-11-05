# Feature Specification: SSO check hook

**Feature Branch**: `feat/005-sso-check-hook`

**Created**: 2026-11-04

**Status**: Implemented

**Input**: User description: "sso-check-hook (Phase 0b, docs/PLAN.md §7; need 6). SessionStart
warning from the local SSO token cache, no network. Exit criteria: tests for valid, expired
and missing cache; p95 < 100 ms."

## Context

"SSO login" was typed about 120 times in 120 days (PLAN.md §1). A session usually finds out
that the cloud login has expired in the middle of a task: a command fails, the user logs in,
and the task is repeated. The cloud CLI keeps its single sign-on tokens in a local cache,
with the time each one expires, so the expiry can be known before anything runs.

This feature warns at the start of a Claude Code session, from that cache alone, which SSO
logins are needed and gives the exact command for each. It never logs in, never touches the
network, and never shows a token (Constitution Principle III). Consolidating the user's
sessions into one is a private runbook task, outside this repository (PLAN.md §7).

The cloud provider is AWS: SSO sessions (`[sso-session <name>]`) and older profiles that
hold their own start URL (`sso_start_url`), as the AWS CLI v2 defines them.

## Clarifications

### Session 2026-11-04

- Q: Without an `sso` section in the configuration, which SSO logins are checked? → A: Every
  SSO session and every older profile with its own start URL in the AWS config; the
  configuration can narrow the list or turn the check off.
- Q: How is an expired access token that the AWS CLI could still renew reported? → A: As
  expired, with the login command: the cache cannot tell whether the portal session is still
  open, and a needless login costs less than a failure in the middle of a task.
- Q: What does the 100 ms 95th percentile cover? → A: The check itself (reading the AWS
  config and the token cache). The whole hook, start-up through the launcher included, stays
  under one second, as the push guard does (spec 004, SC-004); start-up was measured at
  160 to 200 ms.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Warned at session start (Priority: P1)

When a session starts, the user and Claude are told which SSO logins have expired or are
missing, with the exact command to log in for each. When every login is valid, nothing is
said.

**Why this priority**: it is the whole value of the feature: one login before the work
instead of a failed command in the middle of it.

**Independent Test**: build an AWS config and a token cache in a temporary home with a
valid, an expired and a missing token; run the hook's command with a SessionStart event
and check its output for each.

**Acceptance Scenarios**:

1. **Given** every SSO session has a cached token that has not expired, **When** a session
   starts, **Then** the hook says nothing.
2. **Given** a session whose cached token has expired, **When** a session starts, **Then**
   the user sees a warning that names the session, says when it expired in local time, and
   gives the login command (`aws sso login --sso-session <name>`), and Claude gets the same
   facts in its context.
3. **Given** a session with no cached token, **When** a session starts, **Then** the warning
   names it as not logged in, with the same command.
4. **Given** an older profile with its own start URL and an expired or missing token,
   **When** a session starts, **Then** the warning names the profile, with
   `aws sso login --profile <name>`.
5. **Given** several sessions that need a login, **When** a session starts, **Then** there is
   one warning listing each of them once.
6. **Given** no AWS config, or a config without SSO, **When** a session starts, **Then** the
   hook says nothing.

---

### User Story 2 - The check never gets in the way (Priority: P1)

The check is quick, never blocks or slows a session noticeably, and never exposes a token.

**Why this priority**: a hook runs at every session start; one that leaks a token, waits on
the network or breaks the start costs more than the logins it saves.

**Independent Test**: run the check over damaged and unusual inputs (unreadable files,
invalid JSON, a missing expiry, unknown time formats) and check it ends normally with a
note; time it over many runs; check that no token value appears in any output.

**Acceptance Scenarios**:

1. **Given** a cache file that cannot be read or parsed, or has no usable expiry, **When**
   a session starts, **Then** that session is reported as "could not be checked", the
   others are reported normally, and the session starts.
2. **Given** any error inside the check, **When** a session starts, **Then** the session
   starts, and the user sees one line saying the SSO check could not run and why.
3. **Given** any input, **When** the check runs, **Then** no access token, refresh token,
   client secret or other cache value except the expiry appears in its output.
4. **Given** a machine without network, **When** the check runs, **Then** it gives the same
   answer as with network.

---

### User Story 3 - The check follows the user's configuration (Priority: P2)

The user chooses which SSO sessions are checked, or turns the check off, in the private
configuration.

**Why this priority**: the defaults suit most users; the choice matters when some sessions
are rarely used.

**Independent Test**: validate configurations with and without the new section; run the
check with a session list and with the check turned off.

**Acceptance Scenarios**:

1. **Given** no SSO section in the configuration, **When** a session starts, **Then**
   every SSO session and every older SSO profile in the AWS config is checked.
2. **Given** a configuration that lists sessions, **When** a session starts, **Then** only
   those are checked, and a listed name the AWS config does not define is reported as
   unknown.
3. **Given** a configuration that turns the check off, **When** a session starts, **Then**
   the hook says nothing.
4. **Given** a configuration that cannot be read or is invalid, **When** a session starts,
   **Then** the check runs with its defaults and the warning says the configuration was not
   used.

---

### Edge Cases

- **An expired access token that the AWS CLI could still renew** (the cache holds a refresh
  token and its client registration has not expired). Reported as expired, with the login
  command: the cache cannot tell whether the portal session is still open.
- **Expiry formats.** The cache writes `2026-11-04T18:00:00Z` and, in older files,
  `2026-11-04T18:00:00UTC`; both are read, as is any ISO 8601 date and time with a time
  zone (fractional seconds, `+00:00`). Anything else, a time without a zone included, is
  "could not be checked".
- **Several profiles on one SSO session.** The session is checked and listed once.
- **`AWS_CONFIG_FILE`** names another config file: it is read instead of the default.
- **A session that resumes, is cleared or is forked** gets the check too; a compaction does
  not repeat it.
- **The cache directory does not exist.** Every session is "not logged in".
- **Section names** are read the way the AWS CLI reads them: a quoted name loses its
  quotes, a header with more than a kind and a name is not a session, and one name written
  twice is checked once.
- **A cache path that is not a regular file** (such as a named pipe) is "could not be
  checked", unread, so it cannot hold the session start.
- **The plugin cannot start the engine** (no release yet, `uvx` missing, the engine fails or
  takes longer than 8 s): one line says the SSO check could not run and why; the session
  starts.
- **A very large or hostile cache file.** Files above a size limit are "could not be
  checked", unread.

## Requirements *(mandatory)*

### Functional Requirements

#### The hook

- **FR-001**: The plugin MUST ship a SessionStart hook, on session start, resume, clear and
  fork, that runs the engine's SSO check through the launcher (ADR-0022).
- **FR-002**: When at least one checked session needs a login, the hook MUST show the user one
  warning and add the same facts to Claude's context: for each session, its name, its state
  (expired, with the expiry in local time; not logged in; could not be checked, with the
  reason; unknown), and the login command. When none needs a login, it MUST output nothing.
- **FR-003**: The hook MUST always end without blocking the session start. Any error MUST
  become a single line saying the SSO check could not run and why.

#### The check

- **FR-004**: The check MUST find the SSO sessions in the AWS config (`AWS_CONFIG_FILE`, or
  the default file in the user's home): every `[sso-session <name>]` section, and every
  profile with `sso_start_url` and no `sso_session`.
- **FR-005**: The check MUST find each one's cached token where the AWS CLI v2 writes it, and
  read only its expiry (`expiresAt`); an expiry in the past is expired, whatever else the
  file holds.
- **FR-006**: Each checked session MUST get exactly one state: valid, expired, not logged in,
  could not be checked (with the reason), or unknown (listed in the configuration but not
  in the AWS config).
- **FR-007**: The check MUST NOT use the network, run another program, write any file, or
  output any cache value other than an expiry.
- **FR-008**: An engine command MUST print every checked session with its state, for the user
  to run by hand: exit 0 when none needs a login, 1 when one does.

#### Configuration

- **FR-009**: The configuration MUST accept an optional `sso` section, added to schema version
  1 as an additive change (spec 002), with `enabled` (default true) and `sessions` (names of
  SSO sessions or older SSO profiles; default: every one in the AWS config).

#### Proof

- **FR-010**: Tests MUST cover a valid, an expired and a missing token, each acceptance
  scenario above, and each edge case.
- **FR-011**: A test MUST measure the check's time over repeated runs and fail when its 95th
  percentile reaches 100 ms for the check itself (reading the AWS config and the cache), and
  a test MUST fail when the whole hook, start-up through the launcher included, takes one
  second or more.

### Key Entities

- **SSO session**: a name, its kind (an SSO session, or an older profile with its own start
  URL), and where its token is cached.
- **Session state**: valid, expired (with the expiry), not logged in, could not be checked
  (with the reason), or unknown.
- **SSO settings**: the `sso` section: on or off, and which sessions.

## Non-Goals

- **Logging in, renewing a token, or opening a browser.** The user runs the command shown.
- **Any network call**, to AWS or elsewhere.
- **Printing, logging, storing or passing on a token or a secret.** A cache file is parsed
  only to take its expiry and whether it holds a token; nothing else is kept.
- **Changing the AWS config or the token cache**, including consolidating sessions (a private
  runbook task).
- **Providers other than AWS IAM Identity Center** (formerly AWS SSO).
- **Checking long-lived access keys or role credentials.**
- **Warning during a session.** The check runs when a session starts, resumes, is cleared or
  is forked.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a valid, an expired and a missing token, the check gives the right state in
  100 % of the test cases.
- **SC-002**: 0 token or secret values in any output across the test set.
- **SC-003**: The check's 95th percentile time is under 100 ms; the whole hook, start-up
  included, takes under one second.
- **SC-004**: 100 % of the functional requirements are covered by a test.
- **SC-005**: No session start is blocked by the hook in any test.

## Assumptions

- **The AWS CLI v2 cache layout**: tokens are JSON files under `~/.aws/sso/cache/`, named by
  the SHA-1 of the SSO session's name, or of the start URL for an older profile, with an
  `expiresAt` field. This is the CLI's behavior, not a published contract; a change in it
  makes sessions "not logged in" or "could not be checked", never a crash.
- **Local time** is the machine's time zone.
- **Session names** appear in the warning: they are the user's own data shown in the user's
  own session, never written to this repository.
- **No eval suite**: the feature has no skill, so its proof is tests (ADR-0013 covers
  skills).
