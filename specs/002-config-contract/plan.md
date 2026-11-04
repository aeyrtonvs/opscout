# Implementation Plan: Configuration contract

**Branch**: `feat/002-config-contract` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-config-contract/spec.md`

## Summary

The engine gets its first real code: the configuration contract of ADR-0014. Typed,
strict, read-only models hold version 1 of the schema, which is only `schema_version`
(Clarifications). A safe YAML reader keeps every node's position, so each problem is
reported with file, line, column and key path, and never with the value. `opscout config
validate` resolves the directory (flag, `OPSCOUT_CONFIG`, `~/.config/opscout/`) and lists
every problem in one run; `opscout config schema` prints the JSON Schema committed at
`schemas/config.schema.json`, which a drift test keeps equal to the models.
`example-config/` is validated in the local gates and in CI, and a published pre-commit
hook lets the private repository run the same check.

## Technical Context

**Language/Version**: Python ≥ 3.13 (CI also runs 3.15)

**Primary Dependencies**: new runtime dependencies `pydantic` 2 and `pyyaml` 6; new dev
dependencies `types-pyyaml` and `jsonschema` ([research.md](research.md) R7). Otherwise
the standard library (`argparse`, `json`, `pathlib`).

**Storage**: none; reads `<config dir>/config.yaml`

**Testing**: pytest; configurations written to `tmp_path`; the CLI is run in-process and
once as a subprocess for the timing check

**Target Platform**: macOS and Linux (the engine); the same command in GitHub-hosted CI and
in the private repository's pre-commit

**Project Type**: the `opscout` Python package (core, services, entrypoints)

**Performance Goals**: validating the example under 2 s end to end, start-up included
(SC-006)

**Constraints**: offline; problem messages never contain a value (FR-017); only reserved,
fake values in `example-config/` and in tests; nothing from the private configuration in
this repository

**Scale/Scope**: three modules (≈350 lines), their tests, one schema file, one example, one
reference page; 34 requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | The example and every test configuration use reserved values; the private configuration is validated only locally (SC-002); messages never echo values (FR-017) | Pass |
| II. Read-only by construction | Validation only reads one file; no command writes a configuration (Non-Goals) | Pass |
| III. Secrets: existence, never value | No key accepts a secret; credentials are keychain references, and a test enforces it (FR-019, FR-020); validation never reads the keychain | Pass |
| IV. A human approves outward actions | Nothing is sent anywhere; the hook runs in the user's own repository | Pass |
| V. Configuration over code | This feature is Principle V's mechanism: versioned schema, `example-config/` validated in CI, major version and migration note for breaking changes | Pass |
| VI. Deterministic gathering | Typed, tested code; no model involved | Pass |
| VII. Specified, tested, evaluated | Tests first and tied to FRs, with a traceability test; no agent behavior, so no eval suite | Pass |
| VIII. Ports and adapters | Models in `core`, pure parsing and resolution in `services`, file reading in `entrypoints` (R8); no adapter, because nothing external is integrated | Pass |
| IX. Observable runs | No agent run | Not applicable |
| X. Standards; simplicity | YAML, JSON Schema 2020-12, the pre-commit hook format; the envelope only; one file | Pass |

Post-design re-check: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/002-config-contract/
├── spec.md
├── plan.md                  # this file
├── research.md              # R1–R8
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md               # opscout config validate | schema
│   └── config-file.md       # the file format, version 1
├── checklists/requirements.md
└── tasks.md                 # /speckit-tasks
```

### Source Code (repository root)

```text
src/opscout/
├── core/config.py           # Configuration, KeychainRef, Problem, SCHEMA_VERSION, RETIRED_VERSIONS, schema_text()
├── services/config.py       # resolve_config_dir(), parse_config(): YAML walker, version check, error mapping
└── entrypoints/
    ├── config.py            # load_config(directory): reads the file, calls parse_config
    └── cli.py               # `config validate [--config DIR]`, `config schema`

tests/unit/config/
├── test_config_contract.py  # FR markers, traceability test
├── compat/v1/*.yaml         # the compatibility set (FR-030)
└── invalid/                 # (cases are built in the test module, from reserved values)

schemas/config.schema.json   # generated; drift test
example-config/
├── config.yaml              # valid, commented, reserved values
└── README.md                # how to start a private configuration
.pre-commit-hooks.yaml       # opscout-config-validate, for the private repository
.pre-commit-config.yaml      # local hook: validate example-config/ when it or the models change
.github/workflows/ci.yml     # validate example-config/ on every run
justfile                     # `schema` recipe
docs/reference/configuration.md  # the contract for users, and the migration notes
pyproject.toml, uv.lock      # the four dependencies (R7)
AGENTS.md, docs/PLAN.md      # repository map; Phase 0b progress, §4.4 gate row
```

**Structure Decision**: the three package layers of ADR-0011, as R8 describes. The tests go
in `tests/unit/config/`, the first test package for engine code with a spec.

## Design notes

- **Output** (contracts/cli.md): one header line naming the directory and its source, then
  one line per problem, `<file>:<line>:<column>: <key path>: <message>`, or one
  `<file>: valid (schema version 1)` line.
- **Key paths** are dotted, with `[n]` for sequence items; the top level is shown as
  `(top level)`.
- **Problem** is a frozen dataclass in `core`; `parse_config` returns either a
  `Configuration` or a non-empty tuple of problems.
- **Traceability (FR-034)**: the same technique as spec 001: a test reads the `FR-0NN` IDs
  from this spec and compares them with the `spec("002", …)` marks of the module.
- **Timing (SC-006)**: a subprocess runs `python -m opscout config validate --config
  example-config` and must finish under 2 s.

## Complexity Tracking

No violations to justify.
