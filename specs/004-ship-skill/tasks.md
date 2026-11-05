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
- [X] T007 [US1] Write failing tests for `opscout hook pre-tool-use` on scratch repositories:
  the event on stdin, the JSON output, the current and default branches read with git in
  `cwd` or `-C` (FR-007, FR-008); configuration patterns read through the loader, and the
  fixed protections without a configuration (FR-012); an error on a push exits 2, under 1 s
  (FR-013, SC-004); `hooks/hooks.json` declares it with `onFailure: block` (FR-006)
- [X] T008 [US1] Implement `src/opscout/entrypoints/hook.py`, the `hook pre-tool-use` command
  and `plugins/opscout/hooks/hooks.json`; T007 passes; `uv run just plugin` passes

## Phase 4: User Story 3 and 4 — conventions and checks (P2, P3)

- [X] T009 [US3] Write failing tests for `render_rules` and `opscout ship rules` (FR-003): the
  defaults, configured values, always exit 0, deterministic
- [X] T010 [US4] Write failing tests for `check_branch` and `opscout ship check-branch`
  (FR-004) and `check_message` and `opscout ship check-message` (FR-005)
- [X] T011 Implement them in `src/opscout/services/ship.py` and `src/opscout/entrypoints/cli.py`;
  T009–T010 pass; coverage of core and services stays at 100 %
- [X] T012 [P] Add a commented `ship` example to `example-config/config.yaml` and the section
  to `docs/reference/configuration.md`

## Phase 5: User Story 2 — the skill (P1)

- [X] T013 [US2] Write failing tests for `plugins/opscout/skills/ship/SKILL.md`: frontmatter,
  contract first (FR-014), the injected conventions (FR-015), and an `allowed-tools` list that
  holds only its procedure's commands and whose rules match them after substitution (FR-021)
- [X] T014 [US2] Write the skill (procedure of FR-016 to FR-020); T013 passes

## Phase 6: Evals

- [X] T015 Write failing tests for the runner's `scaffold.py` support and `tool_order`
  graders in `tests/tools/test_skill_evals.py`; implement them in `tools/skill_evals.py`
- [X] T016 [US2] Write the eval cases `004-us2-s1` to `004-us2-s6` plus edge cases (nothing
  to commit; asked to push to main) with `scaffold.py` and graders per research R5 (FR-022,
  FR-023), and the structural tests over them
- [X] T017 [US2] Run the suite with the maintainer's confirmation; iterate until every case
  scores ≥ 0.9 above the baseline; record it in the spec's Actuals (FR-024)

## Phase 7: Polish

- [X] T018 [P] Update `AGENTS.md`, `docs/PLAN.md` (status, the row, a paragraph, §9: the
  `bypassPermissions` limit of research R1)
- [X] T019 Run `uv run just check`, `uv run just coverage` and the quickstart
- [X] T020 Remove the traceability `xfail`; set the spec's status to Implemented

## Dependencies

1 → 2 → 3 (the guard, MVP) → 4 → 5 → 6 → 7.

---

## Phase 8: Convergence

- [X] T021 Document `ship check-message -m` in `contracts/commands.md`, per FR-005 (partial)

---

## Phase 9: Independent review

Findings of the review in a fresh context (2026-11-04), each reproduced.

- [X] T022 Deny matching, glob and ambiguous refspecs, and `@`/`HEAD` without a known branch
  (FR-008, high)
- [X] T023 Read git's push configuration in the hook: `push.default`, `remote.<name>.push`,
  the upstream, the push remote (FR-008, high)
- [X] T024 Split commands at operators outside quotes: the skill's own `gh pr create` with a
  scoped title, and commit messages mentioning push, are no longer denied; ordinary commands
  that mention push are left alone (FR-011, high and medium)
- [X] T025 Read `git` by path and deny `git subtree push`; expand `~` after `-C` (FR-010,
  medium)
- [X] T026 Answer events that cannot concern the guard in the launcher, so a launcher that
  cannot start blocks pushes only; any error in the hook exits 2 (FR-013, medium and low)
- [X] T027 Keep `#` lines for `-m` paragraphs; allow capitals and underscores in scopes; note
  unreadable configured patterns in the prompt (FR-005, FR-012, low)
- [X] T028 Strengthen the evals: `no-push-to-main` catches `+main` and `refs/heads/main`,
  the branch comes before any push, and the local remote lives in the run's directory (low)
- [X] T029 Re-run the suite on the final skill and guard; record the result (FR-024)
