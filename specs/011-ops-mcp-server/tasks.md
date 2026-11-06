---
description: "Tasks for the read-only tool server (spec 011)"
---

# Tasks: Read-only tools for the investigation agents

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/tools.md](contracts/tools.md),
[contracts/config.md](contracts/config.md), [quickstart.md](quickstart.md)

**Tests** are mandatory and come first.

- **Marking**: each test is marked `@spec("FR-0NN")`, bound to `"011"`, with one
  requirement per decorator, because the traceability test reads them.
- **No network**: no test uses the network or an AWS account. The AWS tools are tested
  against a fake gateway, the live adapter with botocore's `Stubber`, and the fixture
  adapter with sockets blocked.
- **Fake values only**: `123456789012`, one more fake account ID (allow-listed in T007),
  `example-*` names, RFC 5737 addresses and `example.com`.

## Phase 1: Setup

- [ ] T001 Confirm the baseline on `feat/011-ops-mcp-server`: `uv run just fast` passes.
- [ ] T002 Add the dependencies and their gates (research R1, R2):
  - `uv add "mcp>=2.3,<3"`;
  - `uv add --optional aws "boto3>=1.43,<2"`;
  - a mypy override in `pyproject.toml` that treats `boto3` and `botocore` as untyped;
  - two import-linter contracts in `pyproject.toml`: only `opscout.adapters` imports
    `boto3` and `botocore`, and only `opscout.entrypoints` imports `mcp`;
  - the `dev` dependency group gains `opscout[aws]`, so tests, types and coverage have
    boto3 with no change to `justfile`.

  Then `uv run just fast` must pass. Record the locked versions in research R1 and R2.
- [ ] T003 Create `tests/unit/mcp/test_traceability.py`:
  - every requirement from FR-001 to FR-030 has a test marked with it;
  - the test is marked FR-030;
  - it stays `xfail(strict=True)` until T047.

## Phase 2: Foundational: types, configuration, redaction, ports

- [ ] T004 [P] Write failing tests in `tests/unit/mcp/test_core_tools.py`:
  - **Window** (FR-011, FR-013):
    - `since`/`until` in ISO 8601 with an offset, and `last` as `15m`, `3h` or `2d`;
    - `until` defaults to now;
    - start ≥ end, an end more than 5 minutes ahead, or a naive time are refused;
    - a window longer than the maximum moves its start later and records `capped`.
  - **Caps** (FR-011):
    - the effective value is the configured value, else the default (research R7);
    - a configured value above the ceiling is refused.
  - **Size cap** (FR-011): a result over its character cap drops whole items from the end,
    and `capped` holds `{cap, limit, dropped}`.
  - **Envelope** (FR-013): every time is rendered in the result's timezone, with its
    offset, and the envelope carries `timezone`.
  - **ToolError** (FR-004): every reason in data-model.md has a message, and `fix` only
    where research R8 gives one.
- [ ] T005 Write `src/opscout/core/tools.py` with `ToolSpec`, `Registry` (unique names),
  `Window`, `Caps`, `CAP_CEILINGS`, `Envelope`, `ToolError`, `ErrorReason` and the size
  trimming. T004 passes.
- [ ] T006 [P] Write failing tests in `tests/unit/mcp/test_config.py`:
  - **`alerts.formats`** (FR-014):
    - names are unique and match `[a-z0-9-]`;
    - `recognize` and each field are regular expressions that compile, of at most 500
      characters;
    - each field has exactly one capture group, and only the eleven field names are
      allowed.
  - **`aws.environments`** (FR-015):
    - each `account_id` has 12 digits;
    - names, account IDs and aliases are unique, and aliases are compared without case;
    - each region matches the pattern;
    - `identity` defaults to `own`.
  - **`tools`** (FR-013, FR-010, FR-011):
    - `timezone` defaults to `personal_context.timezone`, then `UTC`;
    - the three `redact` kinds default to false;
    - `caps` stay within the ceilings.
  - **Errors** use spec 002's form, with the messages in contracts/config.md.
  - **Compatibility**: a configuration without the three sections still validates.
- [ ] T007 Add the three sections to `src/opscout/core/config.py` (research R9). T006
  passes. Then:
  - regenerate `schemas/config.schema.json` (`uv run just schema`);
  - add the sections, with fake values, to `example-config/config.yaml`;
  - add a compatibility fixture, `tests/unit/config_contract/compat/v1/tools.yaml`, for spec
    002's contract tests;
  - add one more fake account ID to `tools/leak_allowlist.toml`, with the reason "a second
    fake environment in tests; AWS account IDs must be unique".
- [ ] T008 [P] Write failing tests in `tests/unit/mcp/test_redaction.py`:
  - **Always redacted** (FR-009): private keys, connection strings, credentials and access
    keys, assignments to secret names, secret-shaped values and phone numbers.
  - **Kept by default** (FR-010): account IDs, IP addresses and e-mail addresses, unless
    `tools.redact` turns a kind on.
  - **Structured redaction** (FR-009, research R6):
    - every string leaf in nested dicts and lists is redacted;
    - a key matching a secret name has its value replaced by `[secret]`, whatever its
      type;
    - counts are summed by kind;
    - the result is still valid JSON.
  - **Spec 009 is unchanged**: its redaction tests still pass, with no change.
- [ ] T009 Extend `src/opscout/services/redact.py` with a `keep` set and
  `redact_structure(value, keep)`. T008 passes.
- [ ] T010 [P] Write failing tests in `tests/unit/mcp/test_ports.py` (FR-007):
  - every entry of the service-to-IAM table in `src/opscout/core/aws.py` names a catalog
    action (spec 010's `Catalog`);
  - the table covers every action that a tool in contracts/tools.md declares.
- [ ] T011 Write `src/opscout/core/aws.py` with:
  - `Environment` resolution helpers and `ResourceRef`;
  - the ports `AwsGateway` and `CallLog`, and `GatewayError`;
  - `SERVICE_PREFIX` (research R3), the map from a botocore service to an IAM prefix.

  T010 passes.

## Phase 3: User Story 1: the plugin starts a server whose tools can only read (P1, MVP)

**Goal**: the server, the registry of nine tools with their declarations, the surface proof,
the run-time guard and the plugin's server definition.

**Independent test**: with no configuration, the server lists nine tools. The surface check
passes on the registry and fails on every planted tool. An undeclared call is refused
before it is sent.

- [ ] T012 [P] [US1] Write failing tests in `tests/unit/identity/test_capabilities.py` and
  `tests/unit/identity/test_docs.py` for spec 010's amendment (research R4):
  - `changes` declares `cloudformation:DescribeStackEvents`;
  - a new capability, `inventory`, declares `tag:GetResources` and
    `cloudformation:DescribeStackResources`, with its purpose, agents (alert-triage, ask),
    the readonly identity, and not optional;
  - `opscout identity check` passes on the reference;
  - the summary says `reads 45/45 allowed`, and the read-only identity has 9 policies.

  Update the counts in spec 010's existing tests to the new totals. That is a change in
  the reference, not a weaker check: each assertion keeps its exact value.
- [ ] T013 [US1] Amend spec 010's records. T012 passes.
  - `src/opscout/data/identity/capabilities.json`;
  - `src/opscout/data/identity/aws/readonly/capabilities/changes.json`;
  - a new `src/opscout/data/identity/aws/readonly/capabilities/inventory.json`;
  - the capabilities table and counts in `docs/reference/identity.md`;
  - spec 010's Actuals, with a dated note that spec 011 added the three reads.

  Then `uv run opscout identity check` must print `Pass.`.
- [ ] T014 [P] [US1] Write failing tests in `tests/unit/mcp/test_surface.py`:
  - **The real registry** (FR-006, SC-001): `prove_surface(registry, records)` finds
    nothing.
  - **Planted tools** (FR-006): each of these fails, and the finding names the tool and the
    action:
    - `secretsmanager:GetSecretValue`
    - `lambda:GetFunctionConfiguration`
    - `ecs:DescribeTaskDefinition`
    - `ec2:CreateTags`
    - `ssm:StartSession`
    - an action not in the catalog
    - `cloudwatch:*`
  - **Declarations** (FR-005): a tool with no cloud access declares none.
- [ ] T015 [US1] Write `src/opscout/services/surface.py`. It reuses `Catalog`,
  `readonly_identity` and `proves_allowed`, and refuses wildcards. T014 passes.
- [ ] T016 [P] [US1] Write failing tests in `tests/unit/mcp/test_registry.py`:
  - **The registry** (FR-003, FR-005):
    - nine tools, named as in contracts/tools.md;
    - each has a description, an input schema and an output schema;
    - each declares exactly the actions in contracts/tools.md.
  - **No writes** (FR-008): no handler module imports a write path, and the server writes
    only through `CallLog`, checked by a test that records file opens during a call.
- [ ] T017 [P] [US1] Write failing contract tests in `tests/unit/mcp/test_server.py`,
  through `mcp.Client` connected in-process to the `MCPServer` that
  `opscout.entrypoints.mcp.build_server` returns:
  - **Startup** (FR-002, SC-002): the server lists nine tools, whatever the configuration:
    absent, invalid, or with no cloud. Listing takes less than 2 s, and `boto3` is not in
    `sys.modules` after it.
  - **Invalid input** (FR-003): it returns `invalid-input`, and the handler never runs.
  - **A failing handler** (FR-004): a structured error is returned, and the next call
    succeeds.
  - **Invalid configuration** (FR-004): every tool that needs it returns `invalid-config`,
    with the fix `opscout config validate`.
- [ ] T018 [US1] Write the server, the CLI command and the handlers' skeleton. T016 and T017
  pass.
  - `src/opscout/services/tools/registry.py`: the nine specs and their handlers' skeletons.
  - `src/opscout/services/tools/envelope.py`: applies caps, redaction, timezone and
    identity to every result.
  - `src/opscout/entrypoints/mcp.py`: `build_server(config_loader, gateway_factory,
    call_log)`. Every exception becomes a ToolError, and boto3 is imported lazily.
  - `opscout mcp [--mock DIR]` in `src/opscout/entrypoints/cli.py`.
- [ ] T019 [P] [US1] Write failing tests in `tests/unit/mcp/test_aws_live.py` (FR-007),
  with botocore's `Stubber`:
  - a call whose operation is not in `allowed` is refused before the stubbed response is
    consumed, with reason `undeclared-action`;
  - a declared call goes through;
  - the error mapping of research R8, each with its reason and fix;
  - a throttling error is retried once, then returns `throttled`;
  - the clients use a 5 s connect and 20 s read timeout and `standard` retries with
    `max_attempts=2`.
- [ ] T020 [US1] Write `src/opscout/adapters/aws_live.py`: one session per profile, the
  `before-call` guard through `SERVICE_PREFIX`, the error mapping and the client
  configuration. T019 passes.
- [ ] T021 [P] [US1] Write failing tests in `tests/unit/mcp/test_call_log.py` (FR-008,
  research R11):
  - one line per call, with the time, the tool, the environment, the outcome, the duration
    in ms and the redaction counts;
  - no argument value and no output appears in it, which a test plants a unique marker in
    both to check;
  - a log that cannot be written never fails the call.
- [ ] T022 [US1] Write `src/opscout/adapters/call_log.py`, under the platform state
  directory. T021 passes.
- [ ] T023 [P] [US1] Write failing tests in `tests/unit/mcp/test_plugin.py`:
  - **The server definition** (FR-001, FR-029):
    - `plugins/opscout/.mcp.json` defines one stdio server, `opscout`, run by
      `${CLAUDE_PLUGIN_ROOT}/bin/opscout` with `["mcp"]`;
    - it passes `OPSCOUT_CONFIG` from `${user_config.config_dir}`;
    - it has no `url` and no port.
  - **The launcher** (FR-001):
    - it asks for the `aws` extra in both modes;
    - for `mcp`, a missing `uv` goes to stderr with exit 1 and no hook JSON.
  - **End to end** (FR-029): the command in `.mcp.json` starts against the clone through
    `StdioServerParameters`, and the server lists nine tools.
- [ ] T024 [US1] Write `plugins/opscout/.mcp.json` and update `plugins/opscout/bin/opscout`.
  T023 passes. `uv run just plugin` still passes.

## Phase 4: User Story 2: an alert becomes structured facts and an environment (P1)

**Goal**: `parse_alert`, `resolve_environment` and `list_environments`, with no cloud access.

**Independent test**: the synthetic corpus parses and resolves as expected.

- [ ] T025 [P] [US2] Write failing tests in `tests/unit/mcp/test_alerts.py` for parsing
  (FR-017):
  - each declared format returns its name and the fields it declares, each with
    `{value, source}`;
  - a field whose expression does not match is absent and never guessed;
  - with no format matching, the result is `{"matched": false}`;
  - when two formats match, the first wins and `also_matched` names the other;
  - text beyond 20,000 characters is cut before matching, and the cut is recorded in
    `capped`.
- [ ] T026 [P] [US2] Write failing tests in `tests/unit/mcp/test_resolve.py` for
  resolution (FR-018):
  - an environment is matched by account ID, by name, or by alias, without case;
  - with no match, the result is `out_of_scope`, with the field and value that did not
    match;
  - `list_environments` returns the names, regions, aliases and identity kinds.
- [ ] T027 [US2] Write `src/opscout/core/alerts.py` and the three handlers in
  `src/opscout/services/tools/`. With no `alerts` section, `parse_alert` returns
  `not-configured`. T025 and T026 pass.
- [ ] T028 [US2] Build the synthetic alert corpus in `evals/mcp/alerts/`: fake text in the
  two example formats of contracts/config.md, plus unknown, out-of-scope and two-match
  cases. Each case has an expected-fields file. Add a test that 100 % of the corpus parses
  to its expected fields, or to "no format matched" (SC-005).

## Phase 5: User Story 3: the agent reads evidence, bounded and redacted (P2)

**Goal**: the six AWS tools, against the gateway port.

**Independent test**: each tool, against a fake gateway, returns its contract's data, with
caps, redaction, timezone and identity.

- [ ] T029 [P] [US3] Write failing tests in `tests/unit/mcp/test_alarms.py`:
  - **`read_alarm`** (FR-019): the state, reason, threshold, comparison, metric and
    dimensions; the state history in the window; the data points.
  - **`read_metric`** (FR-020): data points by statistic and period, with the unit, within
    the data-point cap.
  - **Every result** (FR-012, FR-013): times in the configured timezone, and the
    environment and identity kind (`reference identity` or `own identity, not verified`).
- [ ] T030 [P] [US3] Write failing tests in `tests/unit/mcp/test_logs.py` (FR-021,
  FR-011):
  - a query over named groups starts, is polled, and returns its rows and statistics;
  - a window or a row count over its cap is capped and recorded;
  - a query still running at the wait limit is stopped (`StopQuery`), and the result is
    `partial`;
  - a query over 10,000 characters or 11 groups returns `invalid-input`.
- [ ] T031 [P] [US3] Write failing tests in `tests/unit/mcp/test_changes.py` (FR-022,
  research R12):
  - **The sources**: CloudTrail write events (`ReadOnly=false`), the events of stacks
    updated in the window, and, for a resource of a matching type, ECS deployments,
    Auto Scaling activities and RDS events.
  - **The result**: merged newest first; each source capped, with `more` per source.
  - **A resource narrows CloudTrail** by `ResourceName`.
- [ ] T032 [P] [US3] Write failing tests in `tests/unit/mcp/test_resources.py`:
  - **`find_resources`** (FR-024): by tag (`key`, optional `value`), by name (the `Name`
    tag or the ARN's last part), by type; capped, with `more`.
  - **`describe_resource`** (FR-023), for each type in contracts/tools.md: only the
    reviewed fields are returned.
    - An ECS service returns the task definition's ARN, never a call that reads it.
    - A Lambda function is described through its stack, and a function no stack owns
      returns `not-found` with the stack reason.
    - Any other type returns `not-supported` with the list.
  - **Ambiguity** (edge case): several matches are listed up to the cap, and none returns
    `not-found`.
- [ ] T033 [P] [US3] Write failing tests in `tests/unit/mcp/test_envelope.py`:
  - **Redaction** (FR-009, SC-004): planted secret-shaped values in every tool's gateway
    responses never reach an output, and their counts appear.
  - **Size cap** (FR-011): every output stays within 40,000 characters, including a
    gateway response five times larger.
  - **Errors** (edge cases): an unknown environment lists the configured names, and a
    region outside the environment returns `invalid-input`.
  - **Parallel calls**: four calls run concurrently, one fails, and the other three
    succeed.
- [ ] T034 [US3] Write the handlers in `src/opscout/services/tools/alarms.py`, `logs.py`,
  `changes.py` and `resources.py`. Each calls the gateway with only its declared actions.
  T029 to T033 pass.

## Phase 6: User Story 4: skills and evaluations run without any account (P2)

**Goal**: the fixture adapter and the shipped fixtures.

**Independent test**: every tool answers from `evals/mcp/`, with sockets blocked.

- [ ] T035 [P] [US4] Write failing tests in `tests/unit/mcp/test_fixtures.py`:
  - **Lookup** (FR-025): a fixture is found by
    `<environment>/<service-prefix>/<Action>.json`, the first `match` wins, and an `error`
    entry becomes the mapped GatewayError.
  - **No fallback** (FR-026): a missing file or no match returns `fixture-missing`, naming
    the file and the parameters, and nothing goes live. A test patches the live adapter to
    fail if it is called.
  - **Declarations** (FR-007): an action outside `allowed` is refused here too.
- [ ] T036 [US4] Write `src/opscout/adapters/aws_fixtures.py`, and wire `--mock DIR` in
  `src/opscout/entrypoints/mcp.py`. T035 passes.
- [ ] T037 [US4] Write the fixtures in `evals/mcp/aws/example-prod/` (FR-027), with fake
  values only. They cover:
  - every declared action;
  - each cap: a long window, too many rows and an oversized response;
  - a throttled call and an expired login;
  - secret-shaped values in log rows, stack outputs and tags.

  Add `tests/unit/mcp/test_mock.py` (FR-025, SC-005): every tool is called through
  `mcp.Client` in mock mode with sockets blocked, and each returns its contract's data or
  its error.

## Phase 7: User Story 5: a missing or failing integration never blocks anything (P3)

**Goal**: errors that explain and do not spread.

**Independent test**: a broken AWS setup leaves the alert tools working.

- [ ] T038 [P] [US5] Write failing tests in `tests/unit/mcp/test_optional.py`:
  - **No AWS section** (FR-016):
    - every AWS tool returns `not-configured`, with the configuration reference;
    - `parse_alert`, `resolve_environment` and `list_environments` still work.
  - **A broken environment** (US5): one environment with a missing profile and one with an
    expired login, through the stubbed live adapter. Each returns its reason and fix,
    worded as spec 005's login command, and a third, fixture-backed environment still
    answers.
- [ ] T039 [US5] Fill the gaps that T038 finds in `src/opscout/entrypoints/mcp.py` and
  `src/opscout/adapters/aws_live.py`. T038 passes.

## Phase 8: Polish and gates

- [ ] T040 [P] Write `docs/reference/tools.md`, a reference for the user. It covers:
  - what the server is;
  - the nine tools and what they never read;
  - mock mode;
  - the three configuration sections, with fake examples;
  - every error and its fix;
  - caps and redaction;
  - the identity statement (ADR-0023);
  - the call log.

  Link it from `docs/reference/` and from the configuration reference. Then add a test in
  `tests/unit/mcp/test_docs.py` (FR-028): every tool, every error reason and every cap in
  the code appears in the document.
- [ ] T041 Check FR-028 against the suite: for each tool, its schemas, declared actions,
  redaction, caps, mock answer and errors each have a test. Fill any gap.
- [ ] T042 Update `docs/PLAN.md`:
  - **status line**: spec 011 is in progress;
  - **§6**: `.mcp.json`, `evals/mcp/`, and the new core, service and adapter modules;
  - **§7**: an ops-mcp-server paragraph;
  - **§9**: rule 3's gate, the tool allow-lists, exists, proved by the surface check; add
    an open item for the live check (SC-006).
- [ ] T043 Update `AGENTS.md`: rule 3's gate now names the surface check
  (`tests/unit/mcp/test_surface.py`) beside `opscout identity check`, and the repository
  map lists `.mcp.json` and `evals/mcp/`.
- [ ] T044 Run `uv run just check` and `uv run just coverage` (100 % on `core` and
  `services`). Run the quickstart's steps 1 to 5.
- [ ] T045 Converge, then run the independent review of the diff in a fresh context. Record
  the findings and fixes in this file, each reproduced as a test before its fix.
- [ ] T046 Check the staged diff for real data (rule 2). Only reserved values and the
  allow-listed fake account ID may appear. No real alert text, profile, region choice or
  timezone from the private configuration.
- [ ] T047 Remove the traceability `xfail`. Set the spec's status to Implemented, and record
  the effort and the measured counts in its Actuals. SC-006, the live run, is recorded when
  the maintainer runs quickstart step 6.

## Dependencies

1 → 2 → 3 (US1, MVP) → 4 (US2) → 5 (US3) → 6 (US4) → 7 (US5) → 8.

Within each phase, tests come before their implementation. Ordering inside and across
phases:

- **Spec 010's records**: T013 comes before T015, because the surface check proves the
  three new actions.
- **Registry and server**: T018 needs T005, T009 and T011.
- **The live adapter**: T020 needs T011.
- **The plugin**: T024 needs T018.
- **The AWS tools**: T034 needs T018 and T020's error types.
- **Mock mode**: T036 needs T011, and T037 needs T034 and T036.
- **Optional integrations**: T039 needs T036 and T020.
- **Last**: T047.

## Parallel examples

- Phase 2: T004, T006, T008 and T010 together.
- Phase 3: T012, T014, T016, T017, T019, T021 and T023 together, then their
  implementations in dependency order.
- Phase 4: T025 and T026 together.
- Phase 5: T029 to T033 together.

## Implementation strategy

**MVP**: phases 1 to 3. They give the server, the nine declared tools as skeletons, the
surface proof, the run-time guard and the plugin's server definition. This is the gate rule
3 needs before any agent reaches a real system.

Then come the alert tools (US2), which need no cloud, and the AWS tools (US3). After them,
mock mode with the shipped fixtures (US4), which the next spec's evals depend on, and the
error paths (US5).

The live run (SC-006) is a manual step after merge, like spec 010's live check.
