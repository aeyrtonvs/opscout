---
description: "Tasks for the personal context (spec 006)"
---

# Tasks: Personal context

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md)

**Tests**: mandatory and first; `@pytest.mark.spec("006", "FR-0NN")`. Temporary
configuration and target directories only; reserved values only.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/006-personal-context`: `uv run just fast` passes

## Phase 2: Foundational — the `personal_context` section

- [X] T002 Create `tests/unit/context/test_context.py` with the traceability test (FR-011),
  `xfail(strict=True)` until T012
- [X] T003 Write failing tests for `PersonalContext` per data-model.md (FR-001, FR-002):
  optional and additive; at least one field; `timezone` loadable and path-free; one-line
  `language` of 1–40 characters; up to 20 headings of 1–60 characters not starting with `#`;
  1–50 lines of 1–300 characters; no newline or marker text anywhere; a compatibility file
- [X] T004 Implement `PersonalContext` in `src/opscout/core/config.py`, add
  `tests/unit/config_contract/compat/v1/personal_context.yaml`, regenerate the schema

## Phase 3: User Story 1 — render and splice (P1) 🎯 MVP

- [X] T005 [US1] Write failing tests for `render_block` (FR-003, FR-004) and `splice`
  (FR-006, FR-009): the exact block of research R1; optional lines; order kept; a new file;
  appending after a blank line, with and without a final newline; replacing in place with
  bytes outside unchanged; CRLF; every malformed-marker shape with its line
- [X] T006 [US1] Implement `src/opscout/core/context.py` and `src/opscout/services/context.py`
  (`render_block`, `splice`, `confirmation_code`, `unified_diff`); T005 passes

## Phase 4: User Stories 2 and 3 — diff, confirm, write (P1, P2)

- [X] T007 [US2] Write failing tests for `opscout context diff` and `apply` (FR-005, FR-007,
  FR-008): the target from `CLAUDE_CONFIG_DIR`, the default, `--target`; the diff and code;
  exit codes; a terminal yes and no; no terminal without a code; a stale code after the file
  or the configuration changes; the right code; nothing to change; no section; an invalid
  configuration; applying twice changes no byte or modification time (SC-001)
- [X] T008 [US3] Write failing tests for writing (FR-009, FR-010): not UTF-8; above 1 MiB; a
  symbolic link kept and its target changed; permissions kept; a missing directory created;
  a failing replace leaves the old content and no temporary file
- [X] T009 [US2] Implement `src/opscout/entrypoints/context.py` and `context show | diff |
  apply` in `src/opscout/entrypoints/cli.py`; T007 and T008 pass

## Phase 5: Polish

- [X] T010 Update `docs/reference/configuration.md`, `example-config/config.yaml` and
  `docs/PLAN.md` (§7 row and paragraph)
- [X] T011 Run `uv run just check`, `uv run just coverage` and the quickstart
- [X] T012 Remove the traceability `xfail`; set the spec's status to Implemented

## Dependencies

1 → 2 → 3 (render and splice, MVP) → 4 → 5.

---

## Phase 6: Convergence

Ran 2026-11-04 after T012: one gap, the apply command shown after a diff dropped
`--config`; fixed with a test. Otherwise converged.

## Phase 7: Independent review

A review in a fresh context raised 1 high, 4 medium and 7 low findings; each fix has a test.

- [X] T013 A terminal yes recomputes the change and writes only if its code is unchanged;
  `write()` re-reads the target just before the move (FR-008, FR-010)
- [X] T014 Time zones must be listed by the zone database exactly as written (FR-002)
- [X] T015 The diff marks a last line without a newline (FR-007)
- [X] T016 A file ending in a bare carriage return is refused before appending (FR-006)
- [X] T017 The JSON Schema states the heading pattern and "at least one field" (FR-002)
- [X] T018 Lines split at newlines only; Unicode line breaks refused in values; a byte
  order mark kept (FR-002, FR-006)
- [X] T019 End of input or an interrupt at the prompt writes nothing (FR-008)
- [X] T020 A target that is not a regular file is refused; a new file follows the umask; a
  temporary file is removed on any interruption; a dangling link is followed and kept
  (FR-009, FR-010)
- [X] T021 Codes are read without regard to case, and a mismatch says it may be a typo
- Not changed: replacing a file breaks hard links and drops extended attributes, as any
  editor's save does; the zone check reads the zone database from `core` (a validator).
