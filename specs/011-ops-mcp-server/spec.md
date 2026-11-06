# Feature Specification: Read-only tools for the investigation agents

**Feature Branch**: `feat/011-ops-mcp-server`

**Created**: 2026-11-06

**Status**: Draft

**Input**: User description: "ops-mcp-server (Phase 2, PLAN.md §7, needs 1–3; ADR-0010 layer 2,
ADR-0011, ADR-0023). The harness's own local, read-only MCP server, `opscout mcp` over stdio,
started by the plugin's `.mcp.json` through the uv launcher (ADR-0022), so skills and
subagents call typed tools instead of shell commands. It delivers: the server skeleton and a
tool registry in which every tool declares the read-only operations and permissions it uses,
and the surface exposes no write and no secret-value operation, whatever identity it runs
under (the mandatory gate of rule 3 after ADR-0023); redaction of every tool output before it
reaches the model (secret-shaped values, credentials, account IDs per config), reusing spec
009's redaction; a mock mode backed by fixtures so skills and evals run without any account;
optional integrations per ADR-0023 — the AWS integration is enabled only when configured
(environments with profile and region, accounts in scope from the private config), a missing
or failing integration never blocks the server or other tools, and each run states which
identity a tool used (the reference read-only identity or the user's own, as declared in
config; opscout never blocks on it); and the first tools alert triage needs, deterministic
and tested: parse an alert text against formats declared in the config, resolve the account
and environment in scope, CloudWatch alarm and metric reads, CloudWatch Logs Insights queries
with bounded time and result size, recent changes from CloudTrail and CloudFormation, and
describing the deployed configuration of a named resource. Exit criteria: tool contract tests
(schemas, read-only declaration, redaction, mocks); a test proving no registered tool maps to
a write or secret-value API, checked against spec 010's recorded AWS action catalog; the
plugin starts the server and lists its tools. Non-goals: the alert-triage skill itself and
its subagents (next spec), Datadog (use its official read-only MCP server), Kubernetes and
host tools (later specs), cost tools (cost-triage spec), writing anything to any system,
applying or checking the identity, any real account ID, profile or hostname in the
repository."

## Context

Phase 2's agents investigate alerts: they look at metrics, logs, recent changes and the
deployed configuration of the resource that fired. Today a skill could only do that through a
shell, which unattended runs must not have (Constitution Principle II), which cannot be
allowed or denied per operation, and whose output reaches the model unfiltered.

ADR-0023 made the tool surface the mandatory read-only control: whatever identity the user
runs with, the reference one from spec 010 or their own, the tools the agents get can only
read, and never return a secret's value. This feature builds that surface: a local server,
started by the plugin, that offers typed tools, each one declaring the cloud operations it
uses. A check in code proves that every declared operation is one the reference read-only
identity allows, so no tool can write or read a secret even when the identity behind it
could.

The first tools are the ones alert triage needs (PLAN.md §7): understand the alert, find the
environment it belongs to, and read the four kinds of evidence its subagents gather. Each
integration is optional (ADR-0023): with no cloud configured, the server still starts, the
alert tools still work, and the cloud tools say that the cloud is not configured. A mock
mode answers from fixtures, so skills and their evaluations run without any account.

The maintainer's environment, described here only by its shape: one AWS account per
environment, reached through single sign-on profiles; alerts from a CloudWatch notifier and
from an observability platform, posted to chat in fixed text formats; ECS services, Lambda
functions, RDS databases, EC2 hosts and load balancers.

## Clarifications

### Session 2026-11-06

- Q: Account IDs, IP addresses and e-mail addresses in tool outputs: redact them as spec 009
  does, or keep them? → A: configurable by kind. By default they are kept, because an
  investigation needs them as evidence and only the user's own model sees them; the private
  configuration can turn on redaction for each kind. Secrets, credentials, keys and
  secret-shaped values are always redacted (FR-009, FR-010).
- Q: How is the deployed-configuration tool bounded? → A: one reviewed read per resource
  type, for a fixed list: ECS services (without the task definition's contents), RDS
  instances and clusters, EC2 instances, load balancers and target groups, Auto Scaling
  groups, and CloudWatch alarms. Lambda functions are described through the CloudFormation
  stack that created them, never through the function's configuration, which holds its
  environment. Each new type is added with its test (FR-023).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The plugin starts a server whose tools can only read (Priority: P1)

A user who installs the plugin gets the opscout tool server in every Claude Code session,
without configuring anything. The server lists its tools. Each tool says what it does, what
it takes and returns, and which cloud operations it may use. None of those operations can
change anything or return a secret's value, and a test proves it against AWS's own catalog
and the reference identity.

**Why this priority**: this is the mandatory gate of rule 3 (ADR-0023). Without it, no agent
may reach a real system.

**Independent Test**: start a session with the plugin and no opscout configuration; list
the tools; run the surface check over the registry.

**Acceptance Scenarios**:

1. **Given** the plugin is installed and no configuration exists, **When** a session starts,
   **Then** the server starts and lists every tool, and the alert-parsing tool answers that
   no alert format is configured.
2. **Given** the registry, **When** the surface check runs, **Then** every operation every
   tool declares is in AWS's recorded catalog, is not a write, and is allowed by the
   reference read-only identity; a planted tool that declares a write or a secret-value
   operation fails the check, and the failure names the tool and the operation.
3. **Given** a tool, **When** its code calls a cloud operation it did not declare, **Then**
   the call is refused before anything is sent, and the tool returns an error naming the
   operation.

---

### User Story 2 - An alert becomes structured facts and an environment (Priority: P1)

The user pastes an alert, or the agent receives one. A tool recognizes its format from the
formats declared in the private configuration and returns its fields: severity, project,
environment, resource, account, region, metric, threshold and time. A second tool resolves
which configured environment it belongs to, or says that it is out of scope.

**Why this priority**: every investigation starts here, and it needs no cloud access, so it
is useful on its own and testable with fixtures only.

**Independent Test**: run both tools over a corpus of synthetic alerts in each declared
format, plus unknown and out-of-scope ones.

**Acceptance Scenarios**:

1. **Given** an alert in a declared format, **When** it is parsed, **Then** the tool returns
   the format's name and every field the format declares, each with the exact text it came
   from.
2. **Given** an alert that matches no declared format, **When** it is parsed, **Then** the
   tool says so and returns no guessed field.
3. **Given** parsed fields that name an account or environment, **When** they are resolved,
   **Then** the tool returns the configured environment; when no environment matches, it
   returns "out of scope" and the field that did not match.

---

### User Story 3 - The agent reads evidence from the environment, bounded and redacted (Priority: P2)

For an environment the user configured, the agent reads the four kinds of evidence alert
triage needs: the alarm and its metric over a time window; the result of a log query; the
recent changes to the environment (API activity, stack events, deployments); and the
deployed configuration of a named resource. Every result is bounded in time and size, is
redacted before the model sees it, and says which environment and which kind of identity
produced it.

**Why this priority**: it is the evidence the alert-triage spec will cite. It needs the
cloud, so it comes after the parts that do not.

**Independent Test**: run each tool in mock mode against fixtures that hold secret-shaped
values, oversized results and out-of-window data; then once against a live environment.

**Acceptance Scenarios**:

1. **Given** a configured environment and an alarm name, **When** the agent reads the alarm,
   **Then** it gets the alarm's state, its threshold and the metric's values over the
   window, in the stated timezone.
2. **Given** a log query over more than the maximum window or rows, **When** it runs,
   **Then** the window and rows are capped, and the result says what was capped.
3. **Given** a result that holds a credential, a key or a secret-shaped value, **When** it is
   returned, **Then** each such value is replaced by a marker of its kind, and the result
   counts the markers.
4. **Given** an environment declared as using the reference identity, or one with no
   declaration, **When** any cloud tool returns, **Then** the result states the environment
   and "reference identity" or "own identity, not verified"; nothing blocks on it.
5. **Given** a resource name, **When** the agent asks for its deployed configuration,
   **Then** it gets the configuration the reference identity can read, and fields that would
   hold a secret's value are never fetched.

---

### User Story 4 - Skills and evaluations run without any account (Priority: P2)

A developer, or an eval run, starts the server in mock mode with a fixtures directory. Every
cloud tool answers from the fixtures and never reaches the network, so the alert-triage
skill can be built and evaluated before any account is configured.

**Why this priority**: the next spec (alert triage) and its evals depend on it, and the
public repository can only hold fake data.

**Independent Test**: start the server in mock mode with the repository's fixtures, call
every tool, and confirm that no network access happens.

**Acceptance Scenarios**:

1. **Given** mock mode and a fixture for a call, **When** the tool is called, **Then** it
   returns the fixture's data through the same validation, bounds and redaction as a live
   call.
2. **Given** mock mode and no fixture for a call, **When** the tool is called, **Then** it
   returns an error that names the missing fixture, and never falls back to a live call.

---

### User Story 5 - A missing or failing integration never blocks anything else (Priority: P3)

A user with no AWS configured, with an expired login, or with one environment whose profile
is wrong, still gets a working server: the other tools answer, and the failing tool says why
and what command fixes it.

**Why this priority**: ADR-0023 requires it; it mostly shapes errors rather than adding
capability.

**Independent Test**: configure environments with a missing profile, an expired login and an
unreachable region, and call every tool.

**Acceptance Scenarios**:

1. **Given** no AWS configuration, **When** a cloud tool is called, **Then** it returns
   "AWS is not configured" and how to configure it; the alert tools still answer.
2. **Given** an expired single sign-on login, **When** a cloud tool is called, **Then** it
   returns that the login expired and the login command, as spec 005 states it.

---

### Edge Cases

- An alert matches two declared formats: the first declared format wins, and the result
  names the other match.
- An alert names an account ID that belongs to no environment: "out of scope", with the
  account ID as the alert gave it, or its marker when account IDs are redacted.
- A tool is asked for an environment that is not configured: an error listing the configured
  environment names.
- A time window in the future, inverted, or longer than the maximum: the window is refused or
  capped, and the result says which.
- A log query that is still running at the time limit: the query is stopped, and the tool
  returns the rows it has, marked partial.
- The cloud throttles a call: one retry after the delay the cloud asks for, then an error
  that says "throttled".
- A resource name that matches several resources, or none: the tool lists the matches, up to
  a limit, or says none was found.
- Several subagents call tools at the same time: each call is independent, and one call's
  failure does not affect another.
- A fixture or a live result holds a value that looks like a secret inside a field name or a
  log line: it is redacted like any other.
- The configuration is invalid: the server still starts, every tool that needs the
  configuration returns the validation problem, and the error says to run
  `opscout config validate`.

## Requirements *(mandatory)*

### Functional Requirements

#### The server

- **FR-001**: The plugin MUST start the opscout tool server in every Claude Code session,
  through the launcher of ADR-0022, over the standard input and output of a local process.
  It MUST NOT listen on any network port.
- **FR-002**: The server MUST start and list its tools whatever the configuration's state:
  absent, invalid, or with no cloud configured.
- **FR-003**: Each tool MUST have a name, a description, an input schema and an output
  schema. Inputs MUST be validated before anything runs, and outputs MUST be validated
  before they are returned.
- **FR-004**: A tool that fails MUST return a structured error with a reason and, when one
  exists, the command that fixes it. The server MUST keep running after any tool error.

#### The read-only surface

- **FR-005**: Each tool MUST declare every cloud operation it may call, as AWS action names.
  A tool that calls no cloud operation declares none.
- **FR-006**: A check in the test suite MUST prove, for every registered tool, that every
  declared operation is in spec 010's recorded action catalog, is not a write, and is
  allowed by the reference read-only identity (which denies secret values, credentials,
  reads that return plaintext secrets, application data and sessions). It MUST name the tool
  and the operation on failure.
- **FR-007**: At run time, a cloud call whose operation the calling tool did not declare
  MUST be refused before it is sent.
- **FR-008**: No tool MUST write to any system. The only files the server writes are its
  own local run records, if any.

#### Output: redaction, bounds and identity

- **FR-009**: Every tool output MUST pass through redaction before it is returned: private
  keys, connection strings, credentials and access keys, assignments to secret-named keys,
  and secret-shaped values become markers of their kind, counted in the result. This is
  always on.
- **FR-010**: Account IDs, IP addresses and e-mail addresses MUST be kept by default, and
  the configuration MUST be able to turn on redaction for each of the three kinds. A
  redacted value becomes a marker of its kind, counted like the others.
- **FR-011**: Every output MUST be capped in size, and every cloud read MUST be capped in
  time window and in items; the caps have defaults and configurable maximums. A capped
  result MUST say what was capped.
- **FR-012**: Every cloud tool result MUST state the environment it read and the kind of
  identity it used: "reference identity" when the configuration declares that the
  environment uses spec 010's identity, "own identity, not verified" otherwise. opscout
  MUST NOT check, require or block on either.
- **FR-013**: Times in every result MUST be absolute and carry their timezone, and the
  result MUST state the timezone used.

#### Configuration

- **FR-014**: The configuration MUST accept an optional section for alert formats: for each
  format, a name, how to recognize it, and how to extract each field. It is an additive
  change to schema version 1 (spec 002).
- **FR-015**: The configuration MUST accept an optional section for AWS environments: for
  each environment, a name, the account ID, the profile, the region or regions, optional
  aliases that alerts use for it (project or environment names), and whether it uses the
  reference identity. It is an additive change to schema version 1.
- **FR-016**: With no AWS section, every cloud tool MUST return "AWS is not configured" with
  the configuration reference to read; every other tool MUST work.

#### The alert tools

- **FR-017**: A tool MUST parse an alert text against the declared formats and return the
  matching format's name and fields, each with the source text it came from, or say that no
  format matched. It MUST NOT guess a field.
- **FR-018**: A tool MUST resolve parsed fields to a configured environment, by account ID,
  account name or alias, or return "out of scope" with the field that did not match.

#### The AWS tools

- **FR-019**: A tool MUST read an alarm by name: its state, threshold, recent state changes,
  and its metric's values over a window.
- **FR-020**: A tool MUST read a metric by namespace, name and dimensions, with a statistic
  and a period, over a window.
- **FR-021**: A tool MUST run a log query over named log groups and a window, wait for it up
  to a time limit, stop it at the limit, and return its rows, marked partial when stopped.
- **FR-022**: A tool MUST list the recent changes in an environment over a window: API
  activity that changed something, stack events, and service deployments, optionally
  narrowed to a resource.
- **FR-023**: A tool MUST describe the deployed configuration of a named resource, with one
  reviewed read per type, for: ECS services (without the task definition's contents), RDS
  instances and clusters, EC2 instances, load balancers and target groups (with target
  health), Auto Scaling groups, and CloudWatch alarms. A Lambda function MUST be described
  through the resources and outputs of the CloudFormation stack that created it, never
  through the function's own configuration. A type not in the list MUST return "not
  supported" with the supported types. Fields that hold a secret's value MUST NOT be
  fetched.
- **FR-024**: A tool MUST find resources by name or tag in an environment, so the agent can
  turn an alert's resource text into a resource it can describe.

#### Mock mode

- **FR-025**: The server MUST offer a mock mode that answers every cloud tool from a
  fixtures directory, through the same validation, caps and redaction as live calls, and
  never reaches the network.
- **FR-026**: In mock mode, a call with no fixture MUST return an error naming the fixture
  it looked for. It MUST NOT fall back to a live call.
- **FR-027**: The repository MUST ship fixtures with fake values only, covering every tool,
  each cap, a throttled call, an expired login and secret-shaped values.

#### Proof

- **FR-028**: Contract tests MUST cover, for every tool: its schemas, its declared
  operations, redaction of its output, its caps, its mock answers, and its errors.
- **FR-029**: A test MUST prove that the plugin's server definition starts the server
  through the launcher and that the server lists every registered tool.
- **FR-030**: Every requirement of this spec MUST be traced to a test.

### Key Entities

- **Tool**: a named, typed read operation offered to agents, with its declared cloud
  operations.
- **Declared operation**: an AWS action a tool may call; the unit the surface check proves.
- **Alert format**: how to recognize one kind of alert text and extract its fields, declared
  in the private configuration.
- **Environment**: a configured AWS account in scope, with its profile, regions, aliases and
  identity kind.
- **Tool result**: validated, capped and redacted data, with the environment, the identity
  kind, the timezone and what was capped or redacted.
- **Fixture**: a stored answer to one cloud call, used in mock mode.

## Non-Goals

- **Never write**: no tool creates, changes, deletes, tags, starts, stops or sends anything
  to any system. Drafts and messages belong to other specs.
- **Never return a secret's value**: no tool calls an operation the reference identity
  denies, even when the user's own identity would allow it.
- **The alert-triage skill and its subagents**: the next spec.
- **Datadog and other observability platforms**: their official read-only servers are used
  (ADR-0011), configured in later specs.
- **Kubernetes, host commands and cost tools**: later specs (cluster triage, host tools,
  cost-triage).
- **Applying, checking or detecting the identity**: spec 010 checks the reference; this spec
  only states what the configuration declares.
- **Real values in the repository**: no account ID, profile, hostname, alert text or resource
  name from a real environment.
- **A network-reachable server**: local, one process per session, no port.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of the registered tools' declared operations pass the surface check, and
  every planted write or secret-value operation is caught.
- **SC-002**: The server lists its tools within 2 seconds of a session start, with or
  without configuration.
- **SC-003**: Every tool returns a result or an error within 60 seconds.
- **SC-004**: No tool output exceeds its size cap, and no secret-shaped value in the
  fixtures reaches an output.
- **SC-005**: Every tool runs in mock mode with no network access, and 100 % of the
  synthetic alert corpus parses to the expected fields or to "no format matched".
- **SC-006**: With one environment configured live, a user gets an alarm, a metric, a log
  query, recent changes and a resource's configuration through the tools, each stating its
  environment and identity kind.

## Assumptions

- **AWS through named profiles** in the user's AWS configuration, logged in through single
  sign-on or another method the AWS tools already support; opscout stores no credential.
- **One account per environment**, as in spec 010. A tool call names one environment.
- **Alert formats are text** posted to chat, as in the private configuration's samples; a
  format is declared, never learned.
- **The reference identity's catalog and capabilities** (spec 010) define what a tool may
  declare. A tool that needs an operation outside them changes spec 010's capabilities
  first, with their check.
- **Spec 009's redaction** is reused and extended, not replaced.
- **The default timezone** for results is the one the private configuration declares;
  without it, UTC.
