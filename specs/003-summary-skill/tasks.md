---
description: "Tasks for the summary skill (spec 003)"
---

# Tasks: Summary skill

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: mandatory and first (Principle VII); each test carries
`@pytest.mark.spec("003", "FR-0NN")`; eval cases are named after their scenario. Synthetic,
reserved values only.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/003-summary-skill`: `uv run just fast` passes
- [X] T002 Write ADR-0022 (the plugin runs the engine through a uv launcher in `bin/`,
  research R1) in `docs/adr/0022-plugin-runs-the-engine-through-uv.md` and list it in
  `docs/adr/README.md` and PLAN.md §3; close the §9 item on how the plugin finds the package

---

## Phase 2: Foundational — the `writeups` section (US2 data)

- [X] T003 Create `tests/unit/writeups/test_writeups.py` with the traceability test over
  spec 003's FRs, counting test marks and eval cases' `tags` (an eval case names the FRs it
  proves in its `tags`, the one documented frontmatter key for it) (FR-029),
  `xfail(strict=True)` until T021
- [X] T004 Write failing tests: `writeups` is optional and additive (FR-001); its fields and
  bounds per data-model.md (FR-002, FR-003); format names (FR-004); every new field has a
  description and the schema drift test still applies (spec 002); a compatibility file
  `tests/unit/config_contract/compat/v1/writeups.yaml` using every field validates
- [X] T005 Implement `Writeups` and `WriteupFormat` in `src/opscout/core/config.py`, add
  the compatibility file, regenerate `schemas/config.schema.json` (`uv run just schema`);
  T004 and the whole of spec 002's suite pass

---

## Phase 3: User Story 2 — the formats are the user's own (P1)

- [X] T006 [US2] Write failing tests: the built-in formats and shared rules (FR-005), with
  no organization term (FR-007, checked with the leak check's generic rules);
  `resolve_formats` replaces a built-in by name and adds new ones in order (FR-006);
  `render_formats` prints contracts/writeup-formats.md byte for byte for each of the three
  states and is deterministic (FR-008, FR-011)
- [X] T007 [US2] Write failing tests for `opscout writeup formats [--config DIR]`: resolves
  the directory as spec 002 does, an empty `--config` counts as absent (FR-009); always
  exits 0 with the missing, invalid and valid outputs (FR-010); under 2 s from a clone
  (SC-004)
- [X] T008 [US2] Implement `src/opscout/core/writeups.py` (`BUILT_IN_FORMATS`,
  `SHARED_RULES`), `src/opscout/services/writeups.py` (`resolve_formats`,
  `render_formats`) and the `writeup formats` command in `src/opscout/entrypoints/cli.py`;
  T006–T007 pass; coverage of core and services stays at 100 %
- [X] T009 [P] [US2] Add a commented `writeups` example to `example-config/config.yaml`
  (reserved values only) and the section to `docs/reference/configuration.md`

---

## Phase 4: User Story 3 — the plugin runs the engine (P1)

- [X] T010 [US3] Write failing tests for `plugins/opscout/bin/opscout`, running it as a
  subprocess: from the clone it runs this clone's engine (FR-022); from a copy of the plugin
  directory outside a clone, version `0.0.0` prints the no-release message and exits 1
  (FR-024); with a release version it would run `uvx --from opscout==<version>` (checked
  through a fake `uvx` first on PATH) (FR-023); arguments, output and exit status pass
  through (FR-025); the file is Python run through uv and executable (FR-021)
- [X] T011 [US3] Write `plugins/opscout/bin/opscout` (contracts/launcher.md) and
  `plugins/opscout/README.md` (uv required, loading from a clone); T010 passes, and
  `uv run just plugin` passes

---

## Phase 5: User Story 1 — a write-up, ready to paste (P1) 🎯 MVP

- [X] T012 [US1] Write failing tests for `plugins/opscout/skills/summary/SKILL.md`: valid
  Agent Skills frontmatter with only allowed keys, `name` equal to its directory and a
  description within limits (FR-012, research R6); the contract opens the body (FR-013);
  it injects `opscout writeup formats --config "${user_config.config_dir}"` (FR-014);
  `allowed-tools` holds only that command (FR-019, FR-020)
- [X] T013 [US1] Write the skill: contract (deliverable, constraints, non-goals, acceptance),
  the injected formats, and the procedure of FR-015 to FR-019; T012 passes, `uv run just
  plugin` passes
- [X] T014 [US1] Verify in one headless run (`claude -p --plugin-dir plugins/opscout`,
  confirmed by the maintainer) that the injection runs the launcher from `bin/` and what
  `${user_config.config_dir}` becomes when unset; record the result in research R2 and R5,
  and settle how US2 eval cases get a synthetic configuration

---

## Phase 6: Evals (FR-026 to FR-028)

- [X] T015 [US1] Write the eval cases `003-us1-s1` to `003-us1-s6` in
  `plugins/opscout/evals/`, each with a synthetic work log and distinctive fake tokens for
  ruled-out hypotheses, and graders per research R5: `regex` `not_contains` for every
  ruled-out token (FR-016), sections in order and single block (FR-015), the length limit,
  `tool_used: Skill`, and one `llm` grader for "only facts" (FR-027); plus edge cases: an
  unknown kind (FR-017), a secret seen in the session (FR-016), and a request to post it
  (FR-019)
- [X] T016 [US2] Write the eval cases `003-us2-s1` to `003-us2-s5` that concern the skill,
  as settled in T014 (configured formats if an eval can point at a synthetic
  configuration; otherwise covered by T006–T007 and noted in research R5), and the
  invalid-configuration case of FR-018 the same way
- [X] T017 Test that every eval case's name matches a scenario of this spec, that every
  skill scenario has a case, and that every case's frontmatter uses only documented keys
  (FR-026), in `tests/unit/writeups/test_writeups.py`
- [ ] T018 Run the suite with the maintainer's confirmation (quickstart step 4); iterate on
  `SKILL.md` until every case scores ≥ 0.9 and the delta over the baseline is positive;
  record scores, delta and cost in an Actuals section of the spec (FR-028, SC-001 to SC-003)

---

## Phase 7: Polish

- [ ] T019 [P] Update `AGENTS.md` (repository map: `plugins/opscout/bin/`, skills, evals) and
  `docs/PLAN.md` (status line, the summary-skill row and a paragraph, §9)
- [ ] T020 With the maintainer's agreement, add the maintainer's own formats to the private
  configuration and check that it validates and drives the skill locally (SC-005); record
  only the outcome
- [ ] T021 Remove the `xfail` mark from the traceability test (T003); run `uv run just
  check`, `uv run just coverage` and the quickstart; set the spec's status to Implemented

---

## Dependencies & Execution Order

Phase 1 → 2 → 3 → 4 → 5 → 6 → 7. US2's engine side comes before US1 because the skill
injects its output; US3 before US1 because the skill calls the launcher. T014 gates Phase 6.

## Implementation Strategy

Engine first (testable without a model), then the launcher, then the skill, then evals,
which cost quota and run only with the maintainer's confirmation.
