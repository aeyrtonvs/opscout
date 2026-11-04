# Research: Configuration contract

The Technical Context of [plan.md](plan.md) has no open unknowns once the decisions below
are made. Versions were read from PyPI on 2026-11-04.

## R1. How is the YAML read, with positions and without surprises? (FR-005 to FR-010)

**Decision**: PyYAML's safe composer builds the node graph (`yaml.compose` with
`SafeLoader`), and a small walker of our own turns nodes into plain Python data. The
walker:

- records the start mark of every key and value node, keyed by its path, so a problem can
  be located (R3);
- reports a duplicate key at its second occurrence (FR-007);
- accepts only the standard scalar tags (string, integer, float, boolean, null, timestamp)
  plus mappings and sequences; any other tag, explicit or resolved (`!!python/…`,
  `!!binary`, `!!set`, `!!omap`, a local `!tag`) is a problem (FR-006), and so is the merge
  key `<<`, which is a YAML 1.1 extension rather than plain data;
- counts every node it visits, aliases expanded, and stops at 10,000 (FR-010).

Scalars are converted by `SafeLoader`'s own constructors, so `yes`, `0x10` and dates keep
their YAML 1.1 meaning and are then rejected by strict typing where they do not fit
(FR-015). The file is decoded before parsing (`utf-8-sig`, so a byte-order mark is
accepted) and refused above 1 MiB (FR-005).

**Rationale**: `compose` never constructs objects, so no tag can run code, and the node
graph carries line and column marks. Our walker is about 80 lines and gives exactly the
four guarantees the spec asks for.

**Alternatives considered**:

- *ruamel.yaml round-trip loader.* It keeps positions and refuses duplicate keys by
  default, but its API is larger, the positions live on its own container types, and tags
  still need the same filtering. Rejected: more dependency for the same walker.
- *StrictYAML.* It refuses most YAML surprises by design, but it brings its own schema
  language, which would compete with the models as the source of truth (ADR-0014).
  Rejected.
- *`yaml.safe_load`.* No positions and last-duplicate-wins. Rejected.

## R2. What are the models, and what generates the schema? (FR-011, FR-015, FR-021)

**Decision**: Pydantic 2 models in `opscout.core.config`, with
`ConfigDict(strict=True, extra="forbid", frozen=True)`. `schema_version` is
`Literal[1]`, so the schema states `const: 1`. `model_json_schema()` generates the JSON
Schema, which is post-processed only to add `$schema` (draft 2020-12) and `$id`.

**Rationale**: ADR-0014 names typed models with a generated schema. Strict mode gives
FR-015 (no coercion), `extra="forbid"` gives FR-014 and an `additionalProperties: false`
schema, and `frozen` gives the read-only result of FR-032. Pydantic's JSON Schema output
targets draft 2020-12 and carries field descriptions.

**Alternatives considered**:

- *A hand-written JSON Schema validated with `jsonschema`.* Two sources of truth (the schema
  and the typed result the engine uses). Rejected.
- *msgspec.* Fast and strict, but its JSON Schema output and error locations are less
  complete, and the later sections will want validators. Rejected.
- *Dataclasses and a custom validator.* No schema generation. Rejected.

## R3. How does a validation error become a located problem? (FR-014, FR-016, FR-017)

**Decision**: each Pydantic error has a `loc` (a tuple of keys and indices). It is looked up
in the walker's position map:

| Error | Located at |
|---|---|
| unknown key (`extra_forbidden`) | the key node |
| missing key | the mapping that should hold it |
| any other | the value node |

The message is built from the error `type` and its context (`expected` and similar), never
from `input`: an unknown key says "unknown key; it may be a typo or come from a newer
opscout", a wrong type says what was expected. Problems are sorted by line and column.
A test walks the whole set of invalid configurations and asserts that no problem message
contains the offending value (SC-005).

**Rationale**: Pydantic's own `msg` is usually value-free, but not for every error type;
building the text from the type keeps FR-017 a property of our code, not of a dependency.

## R4. How is the schema version checked? (FR-011 to FR-013, FR-031)

**Decision**: before model validation, the walker's top-level mapping is checked:

1. `schema_version` missing → one problem at the top level.
2. Not an integer, or a boolean → one type problem.
3. Above `SCHEMA_VERSION` (1) → one "written for a newer opscout; upgrade" problem.
4. In `RETIRED_VERSIONS` (a mapping from a retired major version to its migration note's
   anchor, empty today) → one problem naming the note.
5. Any other integer that is not `SCHEMA_VERSION` → one "unknown schema version" problem.

Steps 3–5 stop the run for that file (FR-012, FR-013). The parse function takes
`supported` and `retired` as keyword arguments with those defaults, so tests can exercise
a retired version before one exists. A test asserts every `RETIRED_VERSIONS` entry has its
note in `docs/reference/configuration.md` (FR-031).

**Rationale**: a configuration for another major version would otherwise produce a list of
key errors that hides the real cause.

## R5. How is the schema published and kept in step? (FR-021 to FR-025)

**Decision**:

- `opscout config schema` prints the JSON with `indent=2`, `ensure_ascii=False` and a
  final newline; `schemas/config.schema.json` holds exactly that output. `uv run just
  schema` regenerates it.
- `$id` is `https://raw.githubusercontent.com/aeyrtonvs/opscout/main/schemas/config.schema.json`,
  the public repository's own URL.
- The drift test compares the committed file with the generated text and, on failure,
  prints `uv run just schema`.
- A test walks every object in the schema and fails when a property has no description
  (FR-024).
- A test validates `example-config/config.yaml` against the committed file with
  `jsonschema`'s `Draft202012Validator` (FR-025). It runs in `just fast`, so in the
  pre-commit stage and in CI.
- The example's first line is `# yaml-language-server: $schema=../schemas/config.schema.json`;
  `example-config/README.md` gives private repositories the URL form, pinned to a commit.

**Rationale**: a byte comparison is the simplest drift check, and a dependency upgrade that
changes the generated output surfaces as a reviewed diff. A general-purpose validator
proves that the published file, not only the models, accepts the example.

**Alternatives considered**: the `check-jsonschema` pre-commit hook (an extra tool pinned
outside `uv.lock`, against ADR-0020's rule for Python tools); generating the schema in a
build step (nothing to commit, so editors of the private repository have nothing to point
at). Rejected.

## R6. How does the private repository run the check? (FR-033)

**Decision**: a `.pre-commit-hooks.yaml` at this repository's root publishes:

```yaml
- id: opscout-config-validate
  name: opscout configuration
  entry: opscout config validate --config .
  language: python
  files: ^config\.ya?ml$
  pass_filenames: false
```

pre-commit installs this repository's package at the `rev` the private repository pins (a
commit until releases exist) and runs the entry from that repository's root. `--config .`
wins over `OPSCOUT_CONFIG` (FR-001), so the hook validates the files being committed. The
`files` pattern includes `config.yml`, so a misnamed file gets FR-004's hint. A test runs the
hook's entry in a scratch directory with `OPSCOUT_CONFIG` pointing elsewhere.

**Rationale**: the standard way to share a hook (Constitution Principle X), with no
machine-specific path. pre-commit needs the network the first time it installs the hook,
as it already does for gitleaks and actionlint.

**Alternatives considered**: a `repo: local` hook that calls `uvx --from git+…` (every
private repository repeats the command and its pin by hand). Rejected.

## R7. Dependencies (constitution: no dependency without a reason)

| Package | Group | Reason | Version chosen |
|---|---|---|---|
| `pydantic` | runtime | the models and the generated schema (R2, ADR-0014) | `>=2.14.1,<3`, locked at 2.14.1 |
| `pyyaml` | runtime | the YAML composer with positions (R1, ADR-0014) | `>=6.0.3,<7`, locked at 6.0.3 |
| `types-pyyaml` | dev | `mypy --strict` needs PyYAML's stubs | locked at 6.0.12.20260906 |
| `jsonschema` | dev | proves the published schema accepts the example (R5) | `>=4.26`, locked at 4.26.0 |

The locked versions are the newest that are at least 7 days old, the cooldown Dependabot
applies to updates (`.github/dependabot.yml`). pydantic 2.14.2 and the two newest stubs
releases are younger than that; Dependabot will propose them.

## R8. Where does the code live? (ADR-0011, ADR-0021)

**Decision**:

- `opscout.core.config`: the models, `KeychainRef`, `SCHEMA_VERSION`, `RETIRED_VERSIONS`,
  `Problem`, and the schema text. No I/O.
- `opscout.services.config`: `resolve_config_dir(flag, environ, home)` and
  `parse_config(data, file)`. Pure functions: their inputs are passed in, so the coverage
  gate on `services` applies to all of the logic.
- `opscout.entrypoints.config`: `load_config(directory)` reads the file and calls
  `parse_config`; the `config` commands live in `opscout.entrypoints.cli`. Later
  entrypoints (MCP server, daemon) use the same `load_config` (FR-032).

**Rationale**: the import contracts already enforce these layers; reading a file is the
only I/O, and it sits in the composition root.
