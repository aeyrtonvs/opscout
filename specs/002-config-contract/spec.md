# Feature Specification: Configuration contract

**Feature Branch**: `feat/002-config-contract`

**Created**: 2026-11-04

**Status**: Implemented

**Input**: User description: "config-contract (Phase 0b, docs/PLAN.md §7; ADR-0014,
ADR-0002, Constitution Principle V). The configuration contract between the public engine
and a user's private configuration repository. Delivers: typed configuration models in the
engine as the source of truth; a JSON Schema generated from them and committed at
schemas/config.schema.json, with a test that fails when the committed schema drifts from
the models; a loader that resolves the configuration directory in the order --config flag,
then OPSCOUT_CONFIG, then ~/.config/opscout/, reads YAML with a top-level schema_version,
and reports every problem with its file and location; the command `opscout config
validate` (used by this repo's CI against example-config/ and by the private repo's
pre-commit); and example-config/ with obviously fake values only, validated in CI and
pre-commit. The configuration contains no secrets, only keychain service names. Breaking
schema changes require a major schema version and a migration note. Exit criteria: the
example config and a private config validate; the schema drift test passes."

## Context

The engine is public and every organization-specific fact lives in a private configuration
repository (ADR-0002, Constitution Principle I). The two repositories change separately, so
without a contract a change in the engine breaks a private configuration silently and the
failure shows up at run time (ADR-0014). Constitution Principle V requires everything
environment-specific to be expressed in that configuration and validated against a
versioned schema shipped with the engine.

This feature builds the contract itself, not its contents: how the configuration is found,
read, versioned, validated and described to editors, and how both repositories check it.
Each later feature (write-ups, shipping, the SSO check, the daily standup, triage) adds its
own section as an additive change, in its own spec.

## Clarifications

### Session 2026-11-04

- Q: Which sections should version 1 of the configuration schema contain, given that none
  of the features that will read it is specified yet? → A: The envelope only
  (`schema_version`), plus the rules every later section must follow: no secret values, a
  credential is referred to only by its keychain service, and unknown keys are rejected.
  Each later spec adds its own section as an additive change.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A user checks their private configuration before relying on it (Priority: P1)

A user keeps their configuration in a private repository. They run one command, which finds
the configuration directory, reads the configuration file, and either confirms it is valid
or lists every problem at once: the file, the line and column, the path of the key, and
what is wrong. They fix the problems without guessing and without running anything else.

**Why this priority**: it is the contract's reason to exist. A configuration that fails only
at run time, in the middle of an alert triage, is the failure this feature prevents.

**Independent Test**: point the command at a directory holding a valid configuration and
check that it exits successfully; point it at configurations with one or several problems
and check that each problem is reported with its location and that the command fails.

**Acceptance Scenarios**:

1. **Given** a configuration directory whose configuration file is valid, **When** the user
   runs the validate command, **Then** it reports the file it checked and the schema version,
   and succeeds.
2. **Given** a configuration file with several problems (an unknown key, a value of the wrong
   type, a missing required key), **When** the user validates it, **Then** every problem is
   reported in one run, each with its file, line, column and key path, in file order, and
   the command fails.
3. **Given** a configuration file that is not well-formed YAML, **When** the user validates
   it, **Then** the error names the file, line and column of the syntax problem.
4. **Given** no directory was named on the command line, **When** the user validates,
   **Then** the directory comes from `OPSCOUT_CONFIG` if it is set, else from
   `~/.config/opscout/`, and the output says which one was used and why.
5. **Given** the resolved directory does not exist, or has no configuration file, **When**
   the user validates, **Then** the error names the path that was expected and where that
   path came from.

---

### User Story 2 - This repository proves its example configuration is valid (Priority: P1)

A contributor changes the engine. The repository's example configuration, which holds only
obviously fake values, is validated in the local gates and in CI with the same command a
user runs. A change to the models that the example no longer satisfies fails before it
merges.

**Why this priority**: Constitution Principle V and ADR-0014 require it, and it is the
public, runnable template a new user copies to start a private configuration.

**Independent Test**: run the validate command on the example directory and check that it
passes; break the example and check that the local gate and the CI step fail.

**Acceptance Scenarios**:

1. **Given** the example configuration as committed, **When** the gates run, **Then** it
   validates with no problems.
2. **Given** a change that makes the example invalid, **When** the contributor commits or
   opens a pull request, **Then** the gate fails and names the problem.
3. **Given** the example configuration, **When** a new user reads it, **Then** every key is
   explained by a comment, and every value is a reserved or obviously fake one.

---

### User Story 3 - Editors validate the private files while they are written (Priority: P2)

A user edits the configuration in an editor that understands JSON Schema. The engine
publishes a schema, generated from the same models the loader enforces, so the editor
completes keys and flags mistakes as they are typed. The committed schema can never fall
behind the models.

**Why this priority**: it shortens the edit-validate loop, but the validate command already
catches every problem, so it comes second.

**Independent Test**: change a model without regenerating the schema and check that the
suite fails with a message saying how to regenerate; print the schema with the command and
check it equals the committed file; check the example validates against the committed
schema with a general-purpose JSON Schema validator.

**Acceptance Scenarios**:

1. **Given** the models and the committed schema agree, **When** the suite runs, **Then**
   the drift test passes.
2. **Given** a model changed and the schema was not regenerated, **When** the suite runs,
   **Then** the drift test fails and its message gives the command that regenerates it.
3. **Given** the committed schema, **When** a general-purpose JSON Schema validator checks
   the example configuration against it, **Then** the example is valid.
4. **Given** any key in the schema, **When** an editor shows it, **Then** it has a
   description.

---

### User Story 4 - Schema changes are explicit, and old or new configurations fail clearly (Priority: P2)

The engine evolves. Adding an optional section keeps the schema version; removing,
renaming or retyping a key, or making one required, is a breaking change and takes a new
major version with a migration note. A configuration written for a different major version
gets one clear message instead of a list of confusing key errors.

**Why this priority**: two repositories that change separately need it, but the first
breaking change is still in the future.

**Independent Test**: validate configurations whose `schema_version` is higher than the
supported one, lower than it, missing, or not an integer, and check the message for each;
check that every configuration in the compatibility set for the current major version still
validates.

**Acceptance Scenarios**:

1. **Given** a configuration whose `schema_version` is higher than the engine supports,
   **When** it is validated, **Then** the message says the configuration was written for a
   newer opscout and to upgrade, and no other problem is listed.
2. **Given** a configuration whose `schema_version` is a major version an earlier release
   supported, **When** it is validated, **Then** the message names the migration note for
   that version, and no other problem is listed.
3. **Given** a configuration with a key the engine does not know, **When** it is validated,
   **Then** the problem names the key and says it may be a typo or come from a newer
   opscout.
4. **Given** the compatibility set of configurations for the current major version, **When**
   the suite runs, **Then** every one still validates; a change that breaks one fails the
   suite until the major version is raised and a migration note is written.

---

### User Story 5 - The private repository runs the same check on each commit (Priority: P3)

The user's private configuration repository adds one hook, published by this repository,
to its own pre-commit configuration. Every commit that changes the configuration file is
validated with the engine's rules, at a pinned engine revision, before it is recorded.

**Why this priority**: it closes the loop ADR-0014 describes, but it depends on stories 1
and 2 and is adopted in the private repository by its owner.

**Independent Test**: in a scratch repository, reference the published hook, commit a valid
configuration and check that the hook passes; commit an invalid one and check that the
commit is refused with the problems listed.

**Acceptance Scenarios**:

1. **Given** a repository that references the published hook, **When** a commit changes its
   configuration file, **Then** the hook validates that repository's own files, whatever
   `OPSCOUT_CONFIG` says.
2. **Given** an invalid configuration, **When** it is committed, **Then** the commit is
   refused and the problems are listed as in User Story 1.

---

### Edge Cases

- **Empty `OPSCOUT_CONFIG`.** An empty value counts as unset, so the default directory is
  used, and the output says so.
- **A path that is a file, not a directory.** Reported as such, with its source.
- **`config.yml` instead of `config.yaml`.** The missing-file error says a `config.yml` was
  found and that the name must be `config.yaml`.
- **Other files in the directory.** The private deny-list of the leak check, fixtures and
  notes are ignored; only the configuration file is part of the contract.
- **An empty file, a file holding only comments, or a top level that is a list or a
  scalar.** Each is a problem: the top level must be a mapping holding `schema_version`.
- **A duplicate key in the same mapping.** A problem at the second occurrence; YAML's usual
  "last one wins" is not accepted.
- **YAML tags that build objects, and other language-specific features.** Rejected; only
  plain mappings, sequences and scalars are read.
- **Aliases and anchors.** Accepted when they resolve to plain data; a document that expands
  into an unreasonably large structure is rejected rather than expanded.
- **Implicit typing surprises.** `schema_version: "1"`, `schema_version: 1.0` and
  `schema_version: true` are type problems; no value is silently converted to another type.
- **Text that is not valid UTF-8, or a byte-order mark.** Invalid UTF-8 is a problem naming
  the file; a UTF-8 byte-order mark is accepted.
- **A very large file.** Files above a size limit are rejected before parsing, with the
  limit in the message.
- **A secret pasted into the file.** No key accepts a secret value, and an unknown key is a
  problem, so `token: …` cannot pass; the problem message names the key, never the value.
- **Private values in messages.** Problems name keys, types and locations, never the value
  found, so validation output pasted into a ticket or a CI log carries no private fact.
- **`--config` pointing at the example directory while `OPSCOUT_CONFIG` is set.** The flag
  wins.

## Requirements *(mandatory)*

### Functional Requirements

#### Finding the configuration

- **FR-001**: The configuration directory MUST be resolved in this order: the directory
  given on the command line, then `OPSCOUT_CONFIG`, then `~/.config/opscout/`. An empty
  `OPSCOUT_CONFIG` counts as unset.
- **FR-002**: The validate command MUST state the directory it used and which of the three
  sources it came from.
- **FR-003**: A resolved path that does not exist, or is not a directory, MUST be reported
  with the path and its source, and validation MUST fail.
- **FR-004**: The configuration MUST be read from the file `config.yaml` in that directory.
  A missing file MUST be reported with its expected path; if a `config.yml` is present
  instead, the message MUST say so. Other files in the directory MUST be ignored.

#### Reading the file

- **FR-005**: The file MUST be read as UTF-8 (a byte-order mark is accepted). Invalid UTF-8,
  and a file larger than 1 MiB, MUST be reported without parsing.
- **FR-006**: Only plain YAML data MUST be accepted: mappings, sequences and scalars. Tags
  that construct objects MUST be rejected, and reading MUST never run code.
- **FR-007**: A duplicate key in a mapping MUST be a problem, located at its second
  occurrence.
- **FR-008**: A syntax error MUST be reported with its file, line and column.
- **FR-009**: The top level MUST be a mapping. An empty document, a comment-only document,
  or a top level of another kind MUST be a problem.
- **FR-010**: Aliases MUST resolve to plain data; a document whose expansion exceeds a
  fixed limit of nodes MUST be rejected with that limit in the message.

#### Validating the contents

- **FR-011**: `schema_version` MUST be present and MUST be an integer. The engine supports
  exactly one major version at a time; this feature defines version `1`.
- **FR-012**: A `schema_version` higher than the supported one MUST produce a single problem
  saying the configuration was written for a newer opscout and to upgrade; no other problem
  is reported for that file.
- **FR-013**: A `schema_version` lower than the supported one that an earlier release
  supported MUST produce a single problem naming that version's migration note; any other
  integer MUST be reported as an unknown schema version. No other problem is reported.
- **FR-014**: A key the schema does not define MUST be a problem at any depth. Its message
  MUST name the key path and say it may be a typo or come from a newer opscout.
- **FR-015**: Values MUST be checked strictly: a value of the wrong type is a problem and is
  never converted to the expected type.
- **FR-016**: Every problem in a file MUST be reported in one run, except as FR-012 and
  FR-013 state. Each problem MUST give the file, line, column, key path and message, and
  problems MUST be listed in file order.
- **FR-017**: Problem messages MUST NOT include the value found in the file; they name the
  key, the expected type or values, and the location.
- **FR-018**: The validate command MUST exit with status 0 when the configuration is valid,
  1 when it is invalid or cannot be found or read, and 2 on bad arguments.

#### No secrets

- **FR-019**: A key of the schema MUST NOT accept a secret value. A credential MUST be referred
  to only by a keychain reference: the service name, and optionally the account, under
  which the OS keychain stores it.
- **FR-020**: The suite MUST fail when any key of the schema whose name contains, in any
  letter case, `token`, `password`, `passwd`, `secret`, `api_key`, `apikey`, `credential`
  or `private_key` is not a keychain reference.

#### The schema for editors and other tools

- **FR-021**: A JSON Schema MUST be generated from the same models the validator enforces
  and committed at `schemas/config.schema.json`. It MUST declare its JSON Schema dialect, an
  identifier and a title.
- **FR-022**: The suite MUST fail when the committed schema differs from the schema the
  models generate, and the failure MUST give the command that regenerates it.
- **FR-023**: A command MUST print the schema, byte for byte as committed.
- **FR-024**: Every key in the schema MUST have a description, and the suite MUST fail when
  one lacks it.
- **FR-025**: The example configuration MUST validate against the committed schema with a
  general-purpose JSON Schema validator, in the local gates and in CI.

#### The example configuration

- **FR-026**: `example-config/config.yaml` MUST be a valid configuration that uses only
  reserved or obviously fake values (Constitution Principle I), with a comment for every key
  and a line that associates the file with the schema in editors.
- **FR-027**: The example MUST be validated with the validate command in the local gates when
  the example or the models change, and in CI on every run.
- **FR-028**: `example-config/` MUST say how to start a private configuration from it.

#### Evolving the schema

- **FR-029**: The published schema MUST allow exactly one `schema_version`, equal to the
  version the engine supports, and every configuration in the compatibility set MUST
  declare that version. Review rule, stated in the configuration reference: adding an
  optional key or section keeps the version; removing, renaming or retyping a key, or making
  one required, raises the major version and adds a migration note for the old one.
- **FR-030**: A compatibility set of configurations valid under the current major version
  MUST be kept with the tests; every one MUST still validate, so a breaking change fails the
  suite until FR-029 is followed. Each additive change MUST add a configuration that uses
  it.
- **FR-031**: Every major version below the supported one that an earlier release supported
  MUST have a migration note, and the suite MUST fail when one is missing.

#### Using the configuration

- **FR-032**: Every part of the engine that needs the configuration MUST obtain it through
  the same loader and get a typed, read-only result; nothing else parses the file.
- **FR-033**: This repository MUST publish a pre-commit hook that validates a configuration
  repository's own files: the hook validates the repository it runs in, never the directory
  `OPSCOUT_CONFIG` names, and runs when the configuration file changes.

#### Proof

- **FR-034**: Every requirement of this spec MUST be covered by at least one test tied to
  it, and the suite MUST fail when one has none.

### Key Entities

- **Configuration directory**: the directory holding the configuration file; resolved from
  the command line, `OPSCOUT_CONFIG` or the default, and reported with its source. It may
  hold other files, such as the leak check's private deny-list, that are not part of the
  contract.
- **Configuration file**: `config.yaml`, UTF-8 YAML whose top level is a mapping.
- **Configuration**: the validated, typed, read-only content of the file. In version 1 it
  holds only `schema_version`; later specs add sections.
- **Schema version**: an integer major version. Additive changes keep it; breaking changes
  raise it.
- **Problem**: one thing wrong with a configuration: file, line, column, key path and
  message, never the value.
- **Keychain reference**: how a credential is named: a keychain service and an optional
  account, never the secret itself.
- **Published schema**: the JSON Schema generated from the models, committed for editors
  and other tools.
- **Compatibility set**: configurations that must stay valid for as long as the current
  major version lasts.
- **Migration note**: for each retired major version, what changed and how to update a
  configuration.

## Non-Goals

- **Sections beyond the envelope.** Accounts, alert sources, cost scope, schedules, chat,
  write-up formats and the rest come with the specs that use them (decided on 2026-11-04).
- **Wiring the plugin.** The plugin already asks for the configuration directory at install
  time (Phase 0a). Passing it to the MCP server and hooks comes with those components.
- **Reading secrets.** The contract names keychain entries; reading them is the secret
  store's job (daemon-core), and never part of validation.
- **Writing or migrating configurations.** No command creates, edits or upgrades a
  configuration; migration notes are for a person to apply.
- **Changing the private repository.** This repository publishes the hook and the example;
  adopting the hook, and the private configuration itself, stay in the private repository.
  No private value is ever copied here, not even as a test case.
- **Several files, includes, overlays or environment-variable interpolation.** One file,
  read as written.
- **Other formats.** No JSON, TOML or INI configuration.
- **Network access.** Validation runs offline. Publishing the schema to a public catalog is
  out of scope.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The example configuration validates with 0 problems in the local gates and in
  CI, through both the validate command and a general-purpose JSON Schema validator.
- **SC-002**: The maintainer's private configuration validates with the same command, run
  locally; nothing from it reaches this repository.
- **SC-003**: 100 % of model changes made without regenerating the committed schema fail the
  suite.
- **SC-004**: In the test set of invalid configurations (at least 20 cases covering every
  edge case above), 100 % of problems are reported with file, line, column and key path, and
  a file with several problems has all of them reported in one run.
- **SC-005**: 0 values from a configuration appear in any problem message across the test
  set.
- **SC-006**: Validating the example takes under two seconds end to end, start-up included.
- **SC-007**: 100 % of the functional requirements are covered by at least one test tied to
  them.

## Assumptions

- **One file named `config.yaml`.** ADR-0014 fixes YAML and a directory; one file keeps the
  first version simple, and the name is the conventional one.
- **The default directory is `~/.config/opscout/` on every platform**, as ADR-0014 states
  and as the leak check already uses for its deny-list, rather than an OS-specific
  configuration folder.
- **The schema version is an integer major version.** YAML reads `1.10` as a number, so a
  dotted version would be fragile; additive changes are told apart by the compatibility
  set, not by a minor number.
- **Validation prints keys, not values,** so that its output is safe to paste or to keep in
  a CI log, even for a private repository.
- **The private repository's hook installs the engine at a pinned revision.** There are no
  releases yet, so it pins a commit; releases will make tags available.
- **New runtime dependencies** for reading YAML and for typed models with a generated schema
  are needed (ADR-0014 names generated-schema models); the plan records the reason, as the
  constitution requires.
- **Users** are the maintainer and future contributors and users, who know YAML, git and a
  command line.

## Actuals

- **Effort**: one session on 2026-11-04, from specify to the pull request, the same as spec
  001.
- **Tests**: 122 in `tests/unit/config/test_config_contract.py`, every FR traced; 25
  invalid configurations in the test set (SC-004); coverage of `core` and `services` 100 %.
- **Timing**: validating the example takes 0.13 s end to end through `uv run` (SC-006).
- **Private configuration**: validated locally with `opscout config validate` (SC-002); its
  content stays in the private repository.
- **Found while building**: Pydantic accepts `1.0` and `true` for `Literal[1]` even in strict
  mode, and adds a union's member type to error locations (`choice.int`); both are handled
  and tested.

