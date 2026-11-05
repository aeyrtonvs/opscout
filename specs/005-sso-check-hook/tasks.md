---
description: "Tasks for the SSO check hook (spec 005)"
---

# Tasks: SSO check hook

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md)

**Tests**: mandatory and first; `@pytest.mark.spec("005", "FR-0NN")`. AWS configs and
token caches are built in a temporary home with reserved values only.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/005-sso-check-hook`: `uv run just fast` passes

## Phase 2: Foundational — the `sso` section (US3 data)

- [X] T002 Create `tests/unit/sso/test_sso.py` with the traceability test (FR-010),
  `xfail(strict=True)` until T016
- [X] T003 Write failing tests for `Sso` per data-model.md (FR-009): optional and additive;
  `enabled` a strict boolean; `sessions` 1–50 unique names of 1–100 characters without
  whitespace or control characters; a compatibility file using every field
- [X] T004 Implement `Sso` and `Configuration.sso` in `src/opscout/core/config.py`, add
  `tests/unit/config_contract/compat/v1/sso.yaml`, and regenerate the schema
  (`uv run just schema`)

## Phase 3: User Stories 1 and 2 — the check (P1) 🎯 MVP

- [X] T005 [US1] Write failing tests for `find_sessions` and `cache_key` (FR-004, FR-005):
  `sso-session` sections; older profiles with `sso_start_url` and no `sso_session`, once per
  start URL; profiles on one session counted once; `[default]`; nested sub-sections; an empty
  or SSO-less config; an unparsable config raises
- [X] T006 [US1] Write failing tests for `judge` over the R3 table (FR-006): valid, expired
  (both expiry formats; a refresh token does not change it), not logged in (absent; no
  `accessToken`), could not be checked (not JSON, not an object, no or unknown expiry)
- [X] T007 [US2] Write failing tests that no planted token, secret or start URL value appears
  in any state, reason or rendering (FR-007)
- [X] T008 [US1] Implement `src/opscout/core/sso.py` and `find_sessions`, `cache_key`,
  `judge` in `src/opscout/services/sso.py`; T005–T007 pass
- [X] T009 [US1] Write failing tests for `render_warning` and `render_status` (FR-002,
  FR-008): nothing when all are valid; one line per session with local time and the login
  command (`--sso-session` or `--profile`, names shell-quoted); the note when the
  configuration was not used
- [X] T010 [US1] Implement the renderers in `src/opscout/services/sso.py`; T009 passes
- [X] T011 [US2] Write failing tests for `check_sessions` in `src/opscout/entrypoints/sso.py`
  in a temporary home (FR-004, FR-005, FR-007): `AWS_CONFIG_FILE` wins; a missing cache
  directory; an unreadable file and one above 64 KiB are "could not be checked" unread;
  the 95th percentile of 100 runs over 20 sessions under 100 ms (FR-011, SC-003)
- [X] T012 [US2] Implement `src/opscout/entrypoints/sso.py`; T011 passes

## Phase 4: User Story 3 — the configuration (P2)

- [X] T013 [US3] Write failing tests for `select` (FR-009): the default checks every
  session; a list checks only those, matching session names first, then profiles (an older
  profile itself, a profile with `sso_session` its session); unknown names; `enabled: false`

## Phase 5: The commands and the hook

- [X] T014 Write failing tests for `opscout sso check` (FR-008) and `opscout hook
  session-start` (FR-001 to FR-003): exit codes; the JSON with `systemMessage` and
  `additionalContext`; nothing when valid, off or without SSO; an invalid configuration is
  noted and the defaults used; any error becomes the "could not run" message with exit 0;
  `hooks/hooks.json` declares SessionStart with the matcher `startup|resume|clear|fork`; the
  hook through the launcher in under 1 s (SC-003)
- [X] T015 Implement `select` in `src/opscout/services/sso.py`, `session_start` in
  `src/opscout/entrypoints/hook.py`, both commands in `src/opscout/entrypoints/cli.py`, and
  the hook in `plugins/opscout/hooks/hooks.json`; T013 and T014 pass

## Phase 6: Polish

- [X] T016 Remove the traceability `xfail`; update `docs/reference/configuration.md`,
  `example-config/config.yaml`, `plugins/opscout/README.md`, `AGENTS.md` (repository map),
  `docs/PLAN.md` (§7 status and paragraph, §9 if anything opens); set the spec's status to
  Implemented
- [X] T017 Run `uv run just check`, `uv run just coverage` and the quickstart

## Dependencies

1 → 2 → 3 (the check, MVP) → 4 → 5 → 6.

---

## Phase 7: Convergence

Ran 2026-11-04 after T017: converged; every FR, acceptance scenario and edge case had code
and a test.

## Phase 8: Independent review

A review in a fresh context raised 13 findings; each fix has a test.

- [X] T018 The planted token values matched the leak check's ticket-key pattern: renamed
- [X] T019 Tests that showed local dates depended on the machine's time zone: run in UTC
- [X] T020 Section headers split as botocore splits them (quotes, extra words, tabs, one
  name twice) (FR-004)
- [X] T021 The contract's warning text matched to the code, in a form that reads for one
  session too
- [X] T022 Local time per instant, not one fixed offset (FR-002)
- [X] T023 A configuration directory the user named but that is missing is noted; only the
  default place may be absent silently (US3, scenario 4)
- [X] T024 The launcher turns every failure to start the engine into one message, exit 0
  (FR-003)
- [X] T025 Expiries in any ISO 8601 form with a time zone are read; a time without one is
  not (edge case)
- [X] T026 A cache path that is not a regular file is not read; `AWS_CONFIG_FILE` has
  variables expanded (FR-004, FR-007)
- [X] T027 The existing PreToolUse entry of `hooks.json` keeps its formatting
- [X] T028 An unexpected error is named by its type only (FR-007)
- Not changed, as specified: an invalid configuration means defaults, even over
  `enabled: false` (US3, scenario 4); a token about to expire is valid until it expires
  (the AWS CLI renews it within 15 minutes of its expiry while the portal session lasts).
