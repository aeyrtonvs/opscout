---
description: "Tasks for the ship skill (spec 004)"
---

# Tasks: Ship skill

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md)

**Tests**: mandatory and first; `@pytest.mark.spec("004", "FR-0NN")`; eval cases name
their FRs in `tags`. Scratch repositories with a local bare remote only.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/004-ship-skill`: `uv run just fast` passes

## Phase 2: Foundational — the `ship` section (US3 data)

- [X] T002 Create `tests/unit/ship/test_ship.py` with the traceability test (FR-025),
  `xfail(strict=True)` until T020
- [X] T003 Write failing tests for `Ship` and its bounds per data-model.md (FR-001, FR-002),
  a compatibility file using every field, and `draft: false` refused
- [X] T004 Implement `Ship` and `PullRequestConventions` in `src/opscout/core/config.py`,
  defaults in `src/opscout/core/ship.py`, the compatibility file, and regenerate the schema

## Phase 3: User Story 1 — the push guard (P1) 🎯 MVP

- [X] T005 [US1] Write failing tests for `decide_push` (pure) over a table of commands: plain
  pushes asked with the remote and branches named (FR-007); protected destinations by
  refspec, current branch, deletion, pattern and remote default denied (FR-008); `--all`,
  `--mirror`, detached HEAD denied (FR-009); compound, assignments, wrappers, nested shells,
  `eval`, other global options and unsplittable text denied (FR-010); `gh pr create` asked
  and unrelated commands ignored (FR-011)
- [X] T006 [US1] Implement `decide_push` in `src/opscout/services/ship.py`; T005 passes
- [ ] T007 [US1] Write failing tests for `opscout hook pre-tool-use` on scratch repositories:
  the event on stdin, the JSON output, the current and default branches read with git in
  `cwd` or `-C` (FR-007, FR-008); configuration patterns read through the loader, and the
  fixed protections without a configuration (FR-012); an error on a push exits 2, under 1 s
  (FR-013, SC-004); `hooks/hooks.json` declares it with `onFailure: block` (FR-006)
- [ ] T008 [US1] Implement `src/opscout/entrypoints/hook.py`, the `hook pre-tool-use` command
  and `plugins/opscout/hooks/hooks.json`; T007 passes; `uv run just plugin` passes

## Phase 4: User Story 3 and 4 — conventions and checks (P2, P3)

- [ ] T009 [US3] Write failing tests for `render_rules` and `opscout ship rules` (FR-003): the
  defaults, configured values, always exit 0, deterministic
- [ ] T010 [US4] Write failing tests for `check_branch` and `opscout ship check-branch`
  (FR-004) and `check_message` and `opscout ship check-message` (FR-005)
- [ ] T011 Implement them in `src/opscout/services/ship.py` and `src/opscout/entrypoints/cli.py`;
  T009–T010 pass; coverage of core and services stays at 100 %
- [ ] T012 [P] Add a commented `ship` example to `example-config/config.yaml` and the section
  to `docs/reference/configuration.md`

## Phase 5: User Story 2 — the skill (P1)

- [ ] T013 [US2] Write failing tests for `plugins/opscout/skills/ship/SKILL.md`: frontmatter,
  contract first (FR-014), the injected conventions (FR-015), and an `allowed-tools` list that
  holds only its procedure's commands and whose rules match them after substitution (FR-021)
- [ ] T014 [US2] Write the skill (procedure of FR-016 to FR-020); T013 passes

## Phase 6: Evals

- [ ] T015 Write failing tests for the runner's `scaffold.py` support and `tool_order`
  graders in `tests/tools/test_skill_evals.py`; implement them in `tools/skill_evals.py`
- [ ] T016 [US2] Write the eval cases `004-us2-s1` to `004-us2-s6` plus edge cases (nothing
  to commit; asked to push to main) with `scaffold.py` and graders per research R5 (FR-022,
  FR-023), and the structural tests over them
- [ ] T017 [US2] Run the suite with the maintainer's confirmation; iterate until every case
  scores ≥ 0.9 above the baseline; record it in the spec's Actuals (FR-024)

## Phase 7: Polish

- [ ] T018 [P] Update `AGENTS.md`, `docs/PLAN.md` (status, the row, a paragraph, §9: the
  `bypassPermissions` limit of research R1)
- [ ] T019 Run `uv run just check`, `uv run just coverage` and the quickstart
- [ ] T020 Remove the traceability `xfail`; set the spec's status to Implemented

## Dependencies

1 → 2 → 3 (the guard, MVP) → 4 → 5 → 6 → 7.
