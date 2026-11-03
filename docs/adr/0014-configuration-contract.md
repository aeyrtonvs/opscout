---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Configuration contract: a versioned schema, validated in both repositories

## Context and Problem Statement

The engine and the private configuration live in different repositories (ADR-0002). Without a
contract, a change in the engine breaks the configuration silently, and the failure shows up
at run time.

## Decision Outcome

- The configuration is YAML in the private repository, with a top-level `schema_version`.
- Pydantic models in the engine are the source of truth. A JSON Schema generated from them is
  committed at `schemas/config.schema.json`, so editors validate the private files while they
  are written.
- Resolution order: the `--config` flag, then `OPSCOUT_CONFIG`, then
  `~/.config/opscout/`.
- Inside Claude Code, the plugin asks for the configuration directory at install time through
  `userConfig` (type `directory`) and passes it to its MCP server and hooks.
- `opscout config validate` runs in this repository's CI against `example-config/`, and in
  the private repository's pre-commit.
- The configuration contains no secrets, only keychain service names.
- Real samples (`fixtures/`) live in the private repository and feed parser tests and private
  evals.

### Consequences

- Good, because breaking changes are explicit and caught before run time.
- Good, because the private repository gets editor autocompletion and validation.
- Bad, because every breaking schema change needs a migration note.

### Confirmation

CI validates `example-config/`; a test fails when the committed JSON Schema differs from the
models.
