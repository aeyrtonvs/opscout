---
description: "Tasks for the leak guard (spec 001)"
---

# Tasks: Leak guard

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[quickstart.md](quickstart.md)

**Tests**: mandatory and first (Constitution Principle VII). Each test carries
`@pytest.mark.spec("001", "FR-0NN")`. Synthetic leaks are assembled at run time (FR-029):
never write a flagged value literally, in tests or anywhere else.

**Files**: almost every task edits `tests/tools/test_leak_check.py`, so few tasks can run
in parallel. `[P]` marks the ones that touch other files.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/001-leak-guard`: `uv run just fast` passes and
  `uv run --frozen python -m tools.leak_check tracked` exits 0

---

## Phase 2: Foundational

- [X] T002 Tie every existing test in `tests/tools/test_leak_check.py` to the requirements
  it proves with `@pytest.mark.spec("001", "FR-0NN")` (one marker per requirement), using
  the mapping of research.md R4: generic cases → FR-001 to FR-007 and FR-028; allow-list →
  FR-025, FR-026; deny-list → FR-008 to FR-011; config directory → FR-008; identity →
  FR-013, FR-014, FR-017; diff parsing and commits → FR-018, FR-019, FR-021; files and
  names → FR-015, FR-022; redaction → FR-024; message → FR-016; pushed → FR-018; long line
  → FR-031

**Checkpoint**: the suite still passes, now with markers.

---

## Phase 3: User Story 1 — real-looking data is stopped before it is committed (P1) 🎯 MVP

**Goal**: every layer-1 shape is caught in contents, file names and messages, and reserved
values pass.

**Independent test**: `uv run just test tests/tools/test_leak_check.py -k "generic or harmless or hint or typical"`.

- [X] T003 [US1] Add caught cases for every internal suffix and endpoint kind not yet
  covered: `.internal`, `.local`, `.lan`, `.intranet` hostnames (FR-005) and `elb` and
  `execute-api` endpoints (FR-006), in `test_generic_patterns_are_caught`,
  `tests/tools/test_leak_check.py`
- [X] T004 [US1] Add harmless cases: a dotted value with an octet above 255 (FR-002) and a
  chat-ID near miss whose second character is a letter (FR-003), in
  `test_reserved_and_harmless_values_pass`, `tests/tools/test_leak_check.py`
- [X] T005 [US1] Test that a run with two different layer-1 findings prints the shared hint
  once, and a run with a layer-1 and a layer-3 finding prints both hints (FR-023), in
  `tests/tools/test_leak_check.py`
- [X] T006 [US1] Test that every rule name in `RULES` has at least one caught case and one
  harmless case in the parametrized lists (FR-028), and that the test module's own text
  yields no finding (FR-029), in `tests/tools/test_leak_check.py`
- [X] T007 [US1] Test that `python -m tools.leak_check files` over 20 generated files of 50
  lines each, run as a subprocess with `sys.executable` from the repository root, finishes
  in under one second (FR-031, SC-003; research.md R2), in `tests/tools/test_leak_check.py`
- [X] T008 [US1] Make any of T003–T007 that fails for a real reason pass in
  `tools/leak_check.py`, each change starting from the failing synthetic case (FR-027). None did: every layer-1 case passed against the Phase 0a patterns

**Checkpoint**: US1 complete; every layer-1 rule is proven both ways.

---

## Phase 4: User Story 2 — private terms are caught without being published (P1)

**Goal**: deny-list terms are caught everywhere, cannot be allow-listed, and the deny-list
cannot be committed here.

**Independent test**: `uv run just test tests/tools/test_leak_check.py -k denylist`.

- [X] T009 [US2] Test that a deny-list term is caught in a file name and in a commit
  message, in any letter case (FR-009), in `tests/tools/test_leak_check.py`
- [X] T010 [US2] Test that a missing deny-list prints the "layer 2 was skipped" warning on
  standard error and the run continues (FR-010), in `tests/tools/test_leak_check.py`
- [X] T011 [US2] Test that `main` with an invalid deny-list entry exits with status 2 and a
  message naming the line, without scanning (FR-011), in `tests/tools/test_leak_check.py`
- [X] T012 [US2] Test that this repository tracks no file named `leak-denylist.txt` and
  that git ignores that name (FR-012, SC-004), reading the repository root from the test's
  own path, in `tests/tools/test_leak_check.py`
- [X] T013 [P] [US2] Ignore `leak-denylist.txt` in `.gitignore`, under the "Real
  configuration never lives in this repo" heading

**Checkpoint**: US2 complete.

---

## Phase 5: User Story 3 — commit metadata never reveals an employer (P2)

**Goal**: only GitHub no-reply identities pass; the hint names the setting.

**Independent test**: `uv run just test tests/tools/test_leak_check.py -k identity`.

- [X] T014 [US3] Test that `identity` mode passes when git has no identity configured
  (`user.useConfigOnly=true` and no `user.email`), since no commit can be made (FR-017), in
  `tests/tools/test_leak_check.py`

**Checkpoint**: US3 complete (the other scenarios are covered by the T002 markers).

---

## Phase 6: User Story 4 — every commit and pushed ref is checked (P2)

**Goal**: the push and CI checks cover every commit, and the push check covers ref names.

**Independent test**: `uv run just test tests/tools/test_leak_check.py -k "pushed or commits or tracked"`.

### Tests first

- [X] T015 [US4] Tests for ref names in `pushed` mode (FR-032, contracts/cli.md): a local
  branch whose name holds a ticket key fails with a finding located `ref <name>`; a
  `PRE_COMMIT_REMOTE_BRANCH` of `refs/heads/<leaky name>` fails although the local name is
  clean; a leaky tag name fails; a deny-list term in a branch name fails; an allow-listed
  name passes; clean names pass. In `tests/tools/test_leak_check.py`; watch them fail
- [X] T016 [US4] Test that a merge commit is checked against its first parent only, and
  that a commit that only deletes a file holding a leak passes (FR-021, US4 scenario 5), in
  `tests/tools/test_leak_check.py`
- [X] T017 [US4] Test that `tracked` mode checks every tracked file and nothing else
  (FR-020), in `tests/tools/test_leak_check.py`

### Implementation

- [X] T018 [US4] Add `local_ref_names()` to `tools/_git.py`: the short names of every
  `refs/heads/*` and `refs/tags/*`, from `git for-each-ref --format=%(refname:short)`
- [X] T019 [US4] In `tools/leak_check.py`, add `_scan_ref_names(environ, allowlist,
  denylist)`: the names from `PRE_COMMIT_LOCAL_BRANCH`, `PRE_COMMIT_REMOTE_BRANCH` and
  `local_ref_names()`, stripped of `refs/heads/` and `refs/tags/`, deduplicated in order,
  scanned with `scan_line` at location `ref <name>`; call it from `pushed` mode after the
  commit scan; update the module docstring's mode list

- [X] T028 [US4] Found while writing T015: in CI, a finding in a file or ref name still showed
  the whole value inside its location. Test first
  (`test_redaction_also_hides_values_in_file_names`), then redact every found value inside
  locations too, in `Finding.render` in `tools/leak_check.py` (FR-024)

**Checkpoint**: US4 complete; T015–T017 pass.

---

## Phase 7: User Story 5 — false positives openly, patterns only on evidence (P3)

**Goal**: the allow-list needs reasons, and the evidence rule is written where contributors
read it.

**Independent test**: `uv run just test tests/tools/test_leak_check.py -k allowlist`.

- [X] T020 [US5] Test that an allow-list entry without a value stops the run with an error
  naming the entry (FR-025), in `tests/tools/test_leak_check.py`
- [X] T027 [US5] Test that every entry of `tools/leak_allowlist.toml` is still matched by a
  layer-1 rule when the allow-list is left out, so a stale entry fails (FR-027), in
  `tests/tools/test_leak_check.py`
- [X] T021 [P] [US5] State FR-027 in `CONTRIBUTING.md` ("The leak check" section): a pattern
  or harmless-value change starts from a synthetic test case that fails before it; and say
  that the push check also examines branch and tag names (FR-032)
- [X] T022 [US5] State FR-027 in the docstring of `tools/leak_check.py`

**Checkpoint**: all stories complete.

---

## Phase 8: Polish & cross-cutting

- [X] T023 Traceability test (FR-030, SC-005; research.md R3): parse every `FR-0NN` in
  `specs/001-leak-guard/spec.md` and fail if any has no test in
  `tests/tools/test_leak_check.py` marked `spec("001", "FR-0NN")`, in
  `tests/tools/test_leak_check.py`, with no exemptions
- [X] T024 [P] Update `docs/PLAN.md`: the leak-guard row of Phase 0b points at
  `specs/001-leak-guard/` with its status; §9 records the known limit of research.md R1 (a
  push with no new commit runs no pre-commit hook, so its ref names are not checked)
- [X] T025 Run the quickstart (`specs/001-leak-guard/quickstart.md`) and record the
  measured times and the actual effort in `specs/001-leak-guard/spec.md` (PLAN.md §4.3)
- [X] T026 Run `uv run just check` and `uv run just coverage`; both pass

---

## Dependencies & execution order

- T001 → T002 → the story phases.
- Stories are independent of each other once T002 is done; in this repository they run in
  priority order (US1, US2, US3, US4, US5) because they share the test module.
- Inside US4: T015–T017 (tests, failing) → T018 → T019.
- T023 needs every story done (it fails until each FR has a test).
- T024–T026 last.

## Parallel opportunities

- T013 (`.gitignore`) and T021 (`CONTRIBUTING.md`) touch their own files and can run beside
  the test work.
- T024 (`docs/PLAN.md`) can run beside T023.

## Implementation strategy

- **MVP**: Phases 1–3 (US1): the gate is traced and every layer-1 rule proven.
- **Note**: T027 was added by `/speckit-analyze` (finding C1) and T028 during implementation;
  they keep their numbers so the other IDs stay stable.
- **Then**: US2 (private terms), US3 (identity), US4 (the one behavior change, ref names),
  US5 (evidence rule), and the traceability gate that closes SC-005.
- Commit after each phase; each commit passes the gates.
