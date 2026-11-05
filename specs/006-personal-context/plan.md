# Implementation Plan: Personal context

**Branch**: `feat/006-personal-context` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

## Summary

The configuration gains an optional `personal_context` section. The services render it into
a marked block and splice the block into a file's text, both pure (R1, R2). The entrypoints
resolve the target, compute the diff and its confirmation code, and write in one step only
after a terminal yes or a matching `--confirm` (R3, R4). Three commands: `opscout context
show`, `context diff`, `context apply`.

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: none new (`difflib`, `hashlib`, `zoneinfo`, `tempfile`)

**Testing**: pytest, with temporary configuration and target directories

**Constraints**: never write unconfirmed; every byte outside the markers unchanged; one
target file only; reserved values only in tests and examples

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | The facts live in the private configuration; examples are fake | Pass |
| II. Read-only by construction | The only write is the confirmed target; the confirmation is a code check, not a prompt | Pass |
| III. Secrets | The configuration holds none (spec 002); nothing is read from a secret store | Pass |
| IV. A human approves outward actions | Nothing leaves the machine; the local write itself waits for the user | Pass |
| V. Configuration over code | The facts are configuration; the engine renders them | Pass |
| VI. Deterministic gathering | Rendering depends only on the configuration (FR-004) | Pass |
| VII. Specified, tested, evaluated | Tests first; no skill, so no eval suite | Pass |
| VIII. Ports and adapters | Pure render and splice in services; file I/O in entrypoints, like the configuration loader | Pass |
| IX. Observable runs | No unattended run | Not applicable |
| X. Standards; simplicity | A unified diff, HTML-comment markers, no dependency | Pass |

## Project Structure

```text
src/opscout/core/config.py          # PersonalContext; Configuration.personal_context
src/opscout/core/context.py         # markers, limits, MarkerError, PendingChange
src/opscout/services/context.py     # render_block(), splice(), confirmation_code(), unified_diff()
src/opscout/entrypoints/context.py  # target(), pending(), write()
src/opscout/entrypoints/cli.py      # context show | diff | apply
tests/unit/context/test_context.py
tests/unit/config_contract/compat/v1/personal_context.yaml
docs/reference/configuration.md, example-config/config.yaml, schemas/config.schema.json
AGENTS.md (no change), docs/PLAN.md (§7)
```

## Complexity Tracking

No violations to justify.
