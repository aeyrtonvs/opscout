---
description: "Tasks for the daemon core (spec 007)"
---

# Tasks: Daemon core

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md),
[contracts/ports.md](contracts/ports.md), [quickstart.md](quickstart.md)

**Tests**: mandatory and first; `@pytest.mark.spec("007", "FR-0NN")`. Temporary directories
for the configuration, the data, log and cache directories and the agents directory; reserved
values only; no test starts the real `claude` or the real `launchctl`, except the one
macOS-only test of T019.

## Phase 1: Setup

- [X] T001 Confirm the baseline on `feat/007-daemon-core`: `uv run just fast` passes
- [X] T002 Add the runtime dependencies of research R14 with `uv add`: `platformdirs>=4.14,<5`
  locked at 4.14.3 (already in `uv.lock`) and `keyring>=25.7,<26` locked at 25.7.0, in `pyproject.toml` and
  `uv.lock`; check that `mypy --strict` accepts both (record any missing stubs in research
  R14 before going on)
- [X] T003 [P] Create the recorded streams of contracts/ports.md in
  `tests/unit/daemon/streams/*.jsonl`, sanitized from the CLI 2.1.318 runs of research R1–R2
  (fake UUIDs, `cwd` `/tmp/example`, request ids `req_example`, only `builtin` plugins
  except in the user-plugin case, whose path is `/tmp/example/plugins/example`), and
  `tests/unit/daemon/fake_claude.py`, an executable stand-in that records its arguments,
  standard input, environment and working directory, prints one recorded stream per
  attempt and exits with a given status; it reads these settings from `claude.json` beside
  its own copy, since the runner's allow-list drops any test variable

## Phase 2: Foundational — configuration, core types, ports

- [X] T004 Create `tests/unit/daemon/test_traceability.py`: every FR-001 to FR-029 of the
  spec has a test marked with it (FR-026; this test is itself marked FR-026),
  `xfail(strict=True)` until T039. In the same file, a test marked FR-025 that
  `pyproject.toml` holds the forbidden contract of research R13b (`opscout.entrypoints.cli`
  and `opscout.entrypoints.hook` may not import `opscout.adapters` directly) and that
  `lint-imports` passes; it fails until T018 adds the contract
- [X] T005 Write failing tests in `tests/unit/daemon/test_config.py` for the `daemon` section
  per data-model.md (FR-001, FR-002): optional and additive to schema version 1; `jobs`
  "names the engine knows (now only `check`); up to 20"; `enabled` "default true"; `at`
  "`HH:MM`, 00:00–23:59"; `weekdays` "1–7, unique; default every day" from `mon`…`sun`;
  `model` "an alias (`haiku`, `sonnet`, `opus`, `fable`) or a full id `claude-…`"; `budget_usd`
  "> 0 and ≤ 5"; `max_turns` "1–50"; `claude_path` absolute; `secrets` names known (now only
  `claude_token`) with spec 002's `KeychainRef`; unknown keys refused; a compatibility file
- [X] T006 Implement `Daemon` and `JobSettings` in `src/opscout/core/config.py`, add
  `tests/unit/config_contract/compat/v1/daemon.yaml`, regenerate
  `schemas/config.schema.json` (`uv run just schema`); T005 passes
- [X] T007 Write failing tests in `tests/unit/daemon/test_jobs.py` (FR-003, FR-007): the
  period of a daily job is the local date at start, computed once (a start at 23:59:59 that
  ends after midnight keeps its period); the run key `<job>:<period>`; the `check` job's
  default profile (no tools, model `haiku`, budget 0.05, 3 turns, schema from its output
  model) and each JobSettings override; the `check` prompt and rendered text name version,
  model, login source, cost and duration (research R12)
- [X] T008 Implement `src/opscout/core/daemon.py` (Job, RunProfile, StartupReport, RunResult,
  RunnerFacts, RunRecord with `record_version` 1, the outcomes, SecretStatus, InstalledJob,
  SchedulerChange, PendingSchedule, the ports of contracts/ports.md, the `CHECK` job) and the
  period, run key and profile merge in `src/opscout/services/daemon.py`; T007 passes
- [X] T009 [P] Write `tests/unit/daemon/fakes.py`: in-memory fakes of every port, a scripted
  `Runner`, a fixed clock

## Phase 3: User Story 1 — a scheduled job delivers once per period (P1) 🎯 MVP

**Goal**: `opscout run <job>` delivers at most once per period. **Independent test**: with
the fakes, start a job twice for one period, once for the next, and count deliveries.

- [X] T010 [US1] Write failing tests for `run_job` in `tests/unit/daemon/test_run_job.py`
  with the fakes (FR-003 to FR-006, FR-008): scenario 1 delivers and records `delivered`
  with the key; scenario 2 records `skipped` naming the run that delivered, never calls the
  runner; scenario 3, the lock held elsewhere, records `skipped` ("another start holds this
  period"); scenario 4 runs again after `failed` or `inconclusive`; scenario 5, `--force`,
  delivers again and records `forced`; scenario 6, a late start, runs for the current
  period; a delivery failure records `failed`, never `delivered`; every start ends with
  exactly one record and one outcome; the clock moved back still finds the key (edge case)
- [X] T011 [US1] Implement `run_job` in `src/opscout/services/daemon.py` (the outcome
  transitions of data-model.md); T010 passes
- [X] T012 [US1] Write failing tests for `opscout run` in
  `tests/unit/daemon/test_commands.py`, with fake adapters injected into the composition
  root (FR-006, research R13, contracts/commands.md): each output line; exit 0 for
  `delivered` and `skipped`, 1 for the rest, 2 for an invalid configuration (pointing to
  `opscout config validate`), an unknown job (listing the configured ones) and a run store
  that cannot be written (no model run); `--trigger` defaults to `user`
- [X] T013 [US1] Implement `src/opscout/entrypoints/daemon.py` (composition root with
  injectable factories; the data, log and cache directories from `platformdirs`) and the
  `run` command in `src/opscout/entrypoints/cli.py`; T012 passes

**Checkpoint**: the idempotency contract holds with fakes.

## Phase 4: User Story 2 — install, list and remove jobs safely (P1)

**Goal**: the configured jobs match the installed ones after a confirmed install.
**Independent test**: install, install again, change the configuration, install,
uninstall, against a temporary agents directory and a fake service manager.

- [X] T014 [P] [US2] Write failing tests for the wanted property lists in
  `tests/unit/daemon/test_launchd.py` (FR-010, research R5–R6): label `opscout.<job>`; one
  `StartCalendarInterval` entry per weekday (Sunday 0); `ProgramArguments` from a clone
  (`<uv> run --quiet --frozen --project <clone> opscout run <job> --config <dir> --trigger
  scheduler`) and from a release (`<uvx> --quiet --from opscout==<version> …`), with
  absolute programs; `PATH` from the installing environment; log paths; `ProcessType`
  `Background`; no `RunAtLoad`; identical input gives identical bytes; disabled jobs absent
- [X] T015 [P] [US2] Write failing tests for `LaunchdScheduler` with a recording
  `ServiceManager` in `tests/unit/daemon/test_launchd.py` (FR-009, FR-011, FR-013):
  add, update (bootout, write, bootstrap), remove; an up-to-date and loaded job is neither
  written nor reloaded (SC-002); an up-to-date but unloaded job is loaded; files without the
  `opscout.` prefix are never read or changed; a hand-written `opscout.*` file is replaced;
  uninstall removes every `opscout.*` job and a second uninstall changes nothing
- [X] T016 [US2] Move `confirmation_code` from `src/opscout/services/context.py` to
  `src/opscout/services/confirm.py` and import it from both features; spec 006's tests pass
  unchanged (research R11)
- [X] T017 [US2] Write failing tests for `daemon install`, `uninstall` and `status` in
  `tests/unit/daemon/test_commands.py` (FR-009, FR-011, FR-012, FR-029, US2 scenarios 1–8):
  `--dry-run` lists the changes and the code, writes nothing, exit 1; no terminal and no
  code changes nothing and prints the code; a terminal yes applies, a no or end of input
  applies nothing; the change is recomputed after the yes and refused if its code changed;
  a stale code is refused after the configuration or an installed file changes; the right
  code applies; nothing to change exits 0; no jobs configured removes opscout's jobs;
  status names each mismatch (not installed, not configured, schedule differs, not loaded,
  program missing, other engine version) and the last outcome from the run records; with no
  scheduler adapter (non-macOS), install, uninstall and status exit 2 naming it
- [X] T018 [US2] Implement `wanted_plists` and `render_status` in
  `src/opscout/services/daemon.py`, `src/opscout/adapters/launchd.py` (`LaunchdScheduler`,
  `Launchctl` running `/bin/launchctl bootstrap|bootout|print` for `gui/<uid>`), and
  `daemon install | uninstall | status` in `src/opscout/entrypoints/cli.py` (exit 2 with
  "no scheduler is available for this system" off macOS, research R5); add the forbidden
  import contract of research R13b to `pyproject.toml`; T014, T015, T017 and T004's FR-025
  test pass
- [X] T019 [US2] Write the real-launchd test in `tests/unit/daemon/test_launchd.py`
  (marked FR-027, research R5): register the `launchd` marker in `pyproject.toml`; skipped
  unless `sys.platform == "darwin"` and `launchctl print gui/<uid>` succeeds; a unique test label, a property list in a temporary
  directory running `/usr/bin/true`, `Launchctl.load`, `is_loaded`, `unload` in `finally`

**Checkpoint**: idempotent install (exit criterion).

## Phase 5: User Story 3 — restricted, checked model runs (P1)

**Goal**: a model run gets exactly its profile, and a run that started with more is refused.
**Independent test**: the runner against `fake_claude.py` and the recorded streams.

- [X] T020 [P] [US3] Write failing tests for `compare_profile` in
  `tests/unit/daemon/test_runner.py` (FR-015, research R2): the success stream matches;
  each difference is listed and refuses: an extra tool, an MCP server, another permission
  mode, a user plugin, a model outside the alias family, a version below 2.1.318; a
  missing field refuses; a first line that is not the report refuses
- [X] T021 [P] [US3] Write failing contract tests for `ClaudeCliRunner` in
  `tests/unit/daemon/test_runner.py` (FR-014, FR-016 to FR-018, research R1–R3): the exact
  arguments of research R1 in order, for no tools and for declared tools and servers; the
  prompt on standard input only; the working directory is the engine's empty run directory;
  on a refused report the child is terminated and no output kept; an invalid output starts
  one more run whose prompt ends with the validator's message, and a second failure is
  `invalid_output`; the budget stream is `error` with its subtype and errors; the facts
  (version, model, `apiKeySource`, cost and turns summed over attempts, duration, tools
  called); the child environment holds exactly the allow-list of research R1 (each listed
  variable passes when set; `ANTHROPIC_API_KEY`, another `ANTHROPIC_*` or `CLAUDE_CODE_*`
  variable, `AWS_*` and `OPSCOUT_*` set in the engine's environment never pass) plus the
  declared secrets; the executable from `claude_path`, else the search
  path, else an error naming both
- [X] T022 [US3] Implement `compare_profile` in `src/opscout/services/daemon.py` and
  `src/opscout/adapters/claude_cli.py`; T020 and T021 pass
- [X] T023 [US3] Write failing tests in `tests/unit/daemon/test_run_job.py` for the runner's
  outcomes in `run_job` (FR-016, US3 scenarios 2–5): `refused` and `inconclusive` deliver a
  notice and record those outcomes; `error` records `failed` and delivers nothing; then
  wire them in `src/opscout/services/daemon.py` until they pass

**Checkpoint**: restricted profile verified from the start-up report (exit criterion).

## Phase 6: User Story 4 — the harness's secrets stay in the keychain (P2)

**Goal**: secrets are stored once, checked by existence, passed only to the child.
**Independent test**: the keyring adapter on an in-memory backend, and a sentinel value
searched for everywhere.

- [X] T024 [P] [US4] Write failing tests for `KeyringSecretStore` in
  `tests/unit/daemon/test_secrets.py` on an in-memory `keyring` backend (FR-023, research
  R9): `present`, `missing`, `unavailable` (a backend raising `KeyringError` or
  `NoKeyringError`); the account defaults to `opscout`; store then resolve
- [X] T025 [US4] Write failing tests for `secret set` and `secret check` and for runs with
  `claude_token` in `tests/unit/daemon/test_commands.py` (FR-024, US4 scenarios 1–4; the
  token fallback test is also marked FR-019): the
  value read with `getpass` in a terminal, one line of standard input otherwise; check
  prints existence and location only; unknown names exit 2; a configured but missing
  secret fails the run before the runner starts, naming `opscout secret set claude_token`;
  a locked keychain is reported as unavailable; the value reaches only the child's
  `CLAUDE_CODE_OAUTH_TOKEN`; a sentinel value appears in no output, log, record or outbox
  file across the whole daemon test suite (SC-004)
- [X] T026 [US4] Implement `src/opscout/adapters/keychain.py`, the secret resolution in
  `run_job`, and `secret set | check` in `src/opscout/entrypoints/cli.py`; T024 and T025
  pass

## Phase 7: User Story 5 — every run leaves a record (P2)

**Goal**: one complete record per start, readable by status, runs and the session notice.
**Independent test**: each outcome through a job into a temporary run store.

- [X] T027 [P] [US5] Write failing tests for `FileRunStore` and `LocalOutbox` in
  `tests/unit/daemon/test_run_store.py` (FR-004, FR-008, FR-020, FR-021, research R7–R8):
  records under `<data>/runs/<job>/<run-id>.json` with every field of data-model.md and no
  prompt text; a failed write leaves no partial record or temporary file; read back by job
  (newest first) and by key; the lock is exclusive between two processes and released when
  its holder is killed; outbox files under `<data>/outbox/<job>/`; a missing directory is
  created, an unwritable one raises before any model run
- [X] T028 [US5] Write a failing end-to-end test in `tests/unit/daemon/test_run_store.py`:
  two `opscout run check` processes started together on the real file store with
  `fake_claude.py` deliver once (SC-001, exit criterion); a skipped start takes under one
  second (SC-006)
- [X] T029 [US5] Implement `src/opscout/adapters/run_files.py`, `render_runs` and
  `daemon runs` (FR-022); T027 and T028 pass
- [X] T030 [US5] Write failing tests for the session notice in
  `tests/unit/daemon/test_session_notice.py` (FR-028, US5 scenario 5, research R10): a last
  outcome `failed`, `refused` or `inconclusive`; no record for the most recent slot more
  than 15 minutes past and after the job file's modification time; a job configured but
  not installed (macOS only; never off macOS); nothing about jobs when all is well or none
  is configured; the SSO
  warning still comes first; an unreadable run store is reported in one line, never an
  error; the hook stays within spec 005's time budget
- [X] T031 [US5] Implement `session_notices` in `src/opscout/services/daemon.py`, call it from
  `session_start` in `src/opscout/entrypoints/hook.py`, and change the launcher's "could not
  run" wording in `plugins/opscout/bin/opscout` to "opscout's session checks", updating
  spec 005's tests in `tests/unit/sso/test_sso.py`; T030 passes

## Phase 8: Polish and the live check

- [X] T032 [P] Update `docs/reference/configuration.md` (the `daemon` section), create
  `docs/reference/daemon.md` (commands, files and directories, outcomes, the login fallback),
  add the `daemon` example to `example-config/config.yaml`
- [X] T033 [P] Amend `docs/adr/0016-engineering-baseline.md` with the macOS policy (FR-027,
  research R15) and add the CLI facts of research R1–R2 to `docs/PLAN.md` §8
- [X] T034 Run quickstart steps 2–3 on the maintainer's machine with the example and the
  private configuration
- [X] T035 Run quickstart step 4 (FR-019, SC-005): a job installed by `daemon install` runs at
  its time with no one at the keyboard; record whether launchd can use the login in the
  spec's Assumptions and in ADR-0012's "More Information"; if it cannot, run the fallback
  and record that it works
- [X] T036 Run quickstart steps 5–6: the session notice appears for a failed run; uninstall
  leaves no `opscout.*` job
- [X] T037 Update `docs/PLAN.md`: the status line (Phase 0b done, Phase 1 in progress), the
  Phase 1 daemon-core paragraph in §7, §9 (macOS item closed; the login item answered; new
  open items, if any)
- [X] T038 Run `uv run just check` and `uv run just coverage` (90 % on `core` and `services`)
- [X] T039 Remove the traceability `xfail` in `tests/unit/daemon/test_traceability.py`; set
  the status of `specs/007-daemon-core/spec.md` to Implemented and record the effort

## Dependencies

1 → 2 → 3 (US1, MVP) → then 4 (US2), 5 (US3), 6 (US4) and 7 (US5) in any order, except:
T023 needs T011 and T022; T025 needs T022; T028 needs T022 and T029; T030 needs T029;
T034–T036 need every story; T039 last.

## Parallel examples

- Phase 1: T003 beside T002.
- US2: T014 and T015 together; T019 any time after T018.
- US3: T020 and T021 together.
- US4 and US5: T024 and T027 together, once T013 is done.
- Polish: T032 and T033 together.

## Implementation strategy

MVP: phases 1–3, the idempotency contract with fakes. Then US3 (the runner, the riskiest
external contract), US5 (the real store, so the end-to-end test runs), US2 (install), US4
(secrets), and the live check, which needs them all.

## Phase 9: Convergence

- [X] T040 Document the runner's 900-second limit on one Claude Code start (the child is killed and the run ends as `failed`, "Claude Code took longer than 900 s and was stopped") as a decision in research R1 and in `docs/reference/daemon.md` per plan: research R1 (unrequested)

## Independent review (2026-11-05)

A review of the staged diff in a fresh context found no security or data-leak problem, and
these, all fixed with a test first: `--dry-run --confirm` applied the changes (FR-009); an
add did not boot out a job left loaded without its file; a record that cannot be written
after the run was reported as "cannot start" (now named, exit 1); an exception inside the
runner left no record (now `failed`, FR-006); a stop reached only `claude`, not processes
it started (now its process group); the job's `PATH` copied the installing shell's, so
another terminal saw a change (now built from the programs' directories, research R5); the
SC-004 scan ran before the files it searches existed (now `test_zz_sentinel.py`, which also
searches the fake `claude`'s environment log); the session notice read only 20 records (now
100). Kept as is: the two-process test accepts either kind of skip, since which start wins
is not deterministic; the `flock` test between processes proves the lock.
