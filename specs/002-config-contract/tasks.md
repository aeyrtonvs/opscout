---
description: "Tasks for the configuration contract (spec 002)"
---

# Tasks: Configuration contract

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/config-file.md](contracts/config-file.md), [quickstart.md](quickstart.md)

**Tests**: mandatory and first (Constitution Principle VII). Each test carries
`@pytest.mark.spec("002", "FR-0NN")`. Test configurations use reserved, fake values only
(`example_section`, `example-prod`, `not-a-real-value`); nothing from the private
configuration is ever copied here.

**Files**: most tests live in `tests/unit/config/test_config_contract.py`, so few tasks
can run in parallel. `[P]` marks the ones that touch other files.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/002-config-contract`: `uv run just fast` passes
- [X] T002 Add the dependencies of research.md R7 with `uv add` (`pydantic>=2.14.1,<3`,
  `pyyaml>=6.0.3,<7`; dev: `types-pyyaml`, `jsonschema>=4.26`), lock them at the versions
  R7 names, and confirm `uv sync --locked` and `uv run just fast` pass, in `pyproject.toml`
  and `uv.lock`

---

## Phase 2: Foundational

- [X] T003 Create `tests/unit/config/test_config_contract.py` with the traceability test (every `FR-0NN` of
  `spec.md` has a `spec("002", …)` mark and every mark names a real FR, FR-034), marked
  `xfail(strict=True)` until Phase 8 removes the mark
- [X] T004 Write failing tests for the core types: `Configuration` accepts
  `schema_version=1`, is frozen, rejects unknown keys and non-integers without coercion
  (FR-014, FR-015, FR-032); `KeychainRef` takes `service` (1–128 characters, no whitespace
  or control characters) and an optional `account` of the same shape (FR-019); `Problem`
  orders by line then column (FR-016), in `tests/unit/config/test_config_contract.py`
- [X] T005 Implement `src/opscout/core/config.py`: `SCHEMA_VERSION = 1`,
  `RETIRED_VERSIONS: Mapping[int, str] = {}`, `Configuration` and `KeychainRef` as Pydantic
  models with `ConfigDict(strict=True, extra="forbid", frozen=True)` and a description on
  every field, and the frozen `Problem` dataclass (data-model.md); T004 passes

**Checkpoint**: the core types exist and are tested; no I/O yet.

---

## Phase 3: User Story 1 — a user checks their private configuration (P1) 🎯 MVP

**Goal**: `opscout config validate` finds the directory, reads `config.yaml` safely, and
reports every problem with file, line, column and key path, never the value.

**Independent test**: `uv run just test tests/unit/config -k "resolve or read or problem or validate"`.

### Tests (write first, watch them fail)

- [X] T006 [US1] Test `resolve_config_dir(flag, environ, home)`: the flag wins, then a
  non-empty `OPSCOUT_CONFIG`, then `home / ".config/opscout"`, each with its source
  (FR-001, FR-002), in `tests/unit/config/test_config_contract.py`
- [X] T007 [US1] Test `load_config` on a missing directory, a path that is a file, a
  directory without `config.yaml`, and one holding `config.yml` instead (FR-003, FR-004),
  and that other files in the directory are never read (FR-004)
- [X] T008 [US1] Test `parse_config` on bytes: invalid UTF-8, a byte-order mark, a file
  over 1 MiB (FR-005); `!!python/object`, `!!binary`, `!!set`, a local `!tag` and a merge
  key `<<` (FR-006); a duplicate key, located at its second occurrence (FR-007); a syntax
  error with line and column (FR-008); an empty file, a comment-only file, a top-level list
  and a top-level scalar (FR-009); an alias bomb over 10,000 nodes, and a small alias that
  is accepted (FR-010)
- [X] T009 [US1] Test the content problems: `schema_version` missing, `"1"`, `1.0`, `true`
  (FR-011, FR-015); an unknown key at the top level and nested, with the typo-or-newer
  message (FR-014); a file with three problems reports all three in file order, each with
  file, line, column and path (FR-016); no problem message across every invalid case of
  T008 and T009 contains the offending value (FR-017, SC-005); and a test counts the
  invalid cases, at least 20 (SC-004)
- [X] T010 [US1] Test the command in-process: `opscout config validate --config DIR`
  prints the header line with the source and either `valid (schema version 1)` or the
  problem lines of contracts/cli.md; exit 0 valid, 1 invalid or missing, 2 on bad
  arguments (FR-002, FR-018); and that `load_config` returns the same frozen
  `Configuration` the command validated (FR-032)

### Implementation

- [X] T011 [US1] Implement `resolve_config_dir` and `parse_config` in
  `src/opscout/services/config.py`: decode and size check, `yaml.compose` with
  `SafeLoader`, the walker of research.md R1 (positions, duplicates, tags, merge key, node
  limit), the `schema_version` presence and type check of R4, Pydantic validation and the
  error mapping of R3 (messages from the error type, never from `input`); T006, T008, T009
  pass
- [X] T012 [US1] Implement `load_config(directory)` in `src/opscout/entrypoints/config.py`
  (existence checks of FR-003 and FR-004, reads only `config.yaml`) and the `config
  validate` subcommand with `--config` in `src/opscout/entrypoints/cli.py`; T007 and T010
  pass, and the existing smoke tests still pass

**Checkpoint**: US1 works on its own: a configuration directory can be validated.

---

## Phase 4: User Story 2 — the example configuration is valid (P1)

**Goal**: `example-config/` is the public template, validated in the local gates and in CI.

**Independent test**: `uv run opscout config validate --config example-config`.

- [X] T013 [US2] Test that `example-config/config.yaml` validates, that every key in it has
  a comment, that its first line associates the schema, and that `example-config/README.md`
  exists and explains how to start a private configuration (FR-026, FR-028), in
  `tests/unit/config/test_config_contract.py`
- [X] T014 [US2] Test that `.pre-commit-config.yaml` has a local hook that runs `opscout
  config validate --config example-config` when `example-config/`, `schemas/` or
  `src/opscout/` change, and that CI's `gates` job runs it through `just check` without
  skipping it (FR-027)
- [X] T015 [P] [US2] Write `example-config/config.yaml` (schema association line, a comment
  per key, `schema_version: 1`) and `example-config/README.md` (copy into a private
  repository, the schema URL pinned to a commit, the hook of US5); T013 passes
- [X] T016 [US2] Add the local hook to `.pre-commit-config.yaml`; CI's `gates` job already
  runs every pre-commit hook on every file (`just check`); T014 passes, and `uv run just
  check` passes

**Checkpoint**: US2 works: breaking the example fails the gates.

---

## Phase 5: User Story 3 — editors validate while the files are written (P2)

**Goal**: a generated JSON Schema, committed and kept in step with the models.

**Independent test**: `uv run just test tests/unit/config -k schema`.

- [X] T017 [US3] Test `schema_text()`: it declares draft 2020-12, the `$id` of research.md
  R5 and a title (FR-021); the committed `schemas/config.schema.json` equals it, and the
  failure message gives `uv run just schema` (FR-022); `opscout config schema` prints it
  byte for byte (FR-023); every property at any depth has a description, and the checker
  fails on a synthetic schema with a property that lacks one (FR-024); the example
  validates against the committed file with `jsonschema.Draft202012Validator` (FR-025), in
  `tests/unit/config/test_config_contract.py`
- [X] T018 [US3] Implement `schema_text()` in `src/opscout/core/config.py`, the `config
  schema` subcommand in `src/opscout/entrypoints/cli.py`, and the `schema` recipe in
  `justfile`; generate `schemas/config.schema.json`; T017 passes

**Checkpoint**: US3 works: a model change without regeneration fails the suite.

---

## Phase 6: User Story 4 — schema changes are explicit (P2)

**Goal**: other major versions fail with one clear message; breaking changes are caught.

**Independent test**: `uv run just test tests/unit/config -k "version or compat or secret"`.

- [ ] T019 [US4] Test the version checks: `schema_version: 2` gives only the
  newer-opscout problem (FR-012); with `retired={0: "#from-version-0"}` passed in,
  `schema_version: 0` gives only the problem naming that note, and `-1` gives only the
  unknown-version problem (FR-013), in `tests/unit/config/test_config_contract.py`
- [ ] T020 [US4] Test that the committed schema's `schema_version` is `const`
  `SCHEMA_VERSION`, and that every file in `tests/unit/config/compat/v1/` declares that
  version (FR-029); that every one validates and the set holds at least the minimal
  configuration (FR-030); test that every entry
  of `RETIRED_VERSIONS` has its anchor in `docs/reference/configuration.md` (FR-031)
- [ ] T021 [US4] Test the secret rule: the credential-name checker passes the real schema,
  fails a synthetic schema with a `token` string property, and passes one whose `token` is
  a `KeychainRef` (FR-019, FR-020)
- [ ] T022 [US4] Implement the version steps 3–5 of research.md R4 in `parse_config`
  (`supported` and `retired` keyword arguments), the credential-name checker, and
  `tests/unit/config/compat/v1/minimal.yaml`; T019 to T021 pass

**Checkpoint**: US4 works.

---

## Phase 7: User Story 5 — the private repository runs the same check (P3)

**Goal**: a published pre-commit hook.

**Independent test**: `uv run just test tests/unit/config -k hook`.

- [ ] T023 [US5] Test that `.pre-commit-hooks.yaml` publishes `opscout-config-validate`
  with the entry, `language: python`, `files: ^config\.ya?ml$` and `pass_filenames: false`
  of research.md R6, and that running its entry in a scratch directory validates that
  directory even when `OPSCOUT_CONFIG` names another one (FR-033), in
  `tests/unit/config/test_config_contract.py`
- [ ] T024 [P] [US5] Write `.pre-commit-hooks.yaml`; T023 passes

**Checkpoint**: every story works.

---

## Phase 8: Polish and cross-cutting

- [ ] T025 Test that `python -m opscout config validate --config example-config`, run as a
  subprocess, finishes under 2 s (SC-006), in `tests/unit/config/test_config_contract.py`
- [ ] T026 [P] Write `docs/reference/configuration.md`: where the configuration is found,
  the file format, version 1, the rules for later sections (additive and breaking changes,
  keychain references, descriptions), the private repository's hook, and an empty
  "Migration notes" section (FR-029, FR-031)
- [ ] T027 [P] Update the repository map in `AGENTS.md` (`example-config/`, `schemas/`
  exist), and `docs/PLAN.md`: status line, the config-contract row and a paragraph on what
  it delivered, the §4.4 row for `example-config/`, and the dependencies' reason
- [ ] T028 Remove the `xfail` mark from the traceability test (T003); every FR has a test
- [ ] T029 Run the quickstart's steps 1–4, `uv run just check` and `uv run just coverage`;
  record the actuals (effort, timing) in an Actuals section of `spec.md` and set its status
  to Implemented
- [ ] T030 With the maintainer's agreement, validate the private configuration locally
  (quickstart step 5, SC-002); record only the outcome, never its content

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → Phase 3 (MVP). Phases 4–7 depend on Phase 3; Phase 4 also needs
  T018's schema file for its association line to resolve, but not for its tests. Phase 8
  comes last.
- Within each story, tests come before the code that makes them pass.

### Parallel opportunities

- T015 (example files) alongside T013–T014.
- T024 (hook file) alongside T023.
- T026 and T027 (documentation) alongside each other.

## Implementation Strategy

1. **MVP**: Phases 1–3. A configuration directory can be validated with located problems.
2. Add US2 (the example in the gates), then US3 (the schema), then US4 (versions and the
   compatibility set), then US5 (the hook).
3. Polish, then `/speckit-converge` and an independent review before the pull request.
