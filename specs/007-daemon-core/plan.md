# Implementation Plan: Daemon core

**Branch**: `feat/007-daemon-core` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

## Summary

The configuration gains an optional `daemon` section (jobs, Claude Code path, secrets).
`core` defines the jobs, the run profile, the run record and five ports; `services` runs a
job for its period through those ports: lock, "already delivered?", secrets, runner, one
retry, delivery, record (R3, R7). Adapters: `ClaudeCliRunner` starts the user's own
`claude -p` with every restriction explicit and refuses any run whose start-up report does
not match (R1, R2); files under `platformdirs` hold the records and the outbox (R7, R8);
`keyring` holds the harness's secrets (R9); launchd installs the jobs, behind a seam that
tests replace (R5, R6). Commands: `opscout run <job>`, `opscout daemon install | uninstall |
status | runs`, `opscout secret set | check`. The SessionStart hook also reports jobs that
failed or did not run (R10). One job ships, `check`, which proves the path and settles the
login question live (R4, R12).

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: new at run time `platformdirs` and `keyring` (R14, as ADR-0021
justifies); standard library `plistlib`, `fcntl`, `subprocess`, `getpass`, `hashlib`

**Storage**: JSON run records and Markdown outbox files under the user's data directory;
launchd property lists in `~/Library/LaunchAgents` (macOS)

**Testing**: pytest; fakes for every port; a fake `claude` script that prints recorded,
sanitized streams; a fake `ServiceManager`; an in-memory `keyring` backend; one
real-launchd test, macOS only (R5, R15)

**Target Platform**: macOS (launchd); the engine and its tests run on Linux too

**Project Type**: CLI and library (the engine), plus the plugin's existing hook

**Performance Goals**: a skipped start under 1 s (SC-006); the SessionStart hook stays under
its time limit (spec 005)

**Constraints**: never deliver twice for one period without `--force`; never trust an
unchecked run; no secret value in any output, log or record; nothing outside the `opscout.`
prefix touched; install and uninstall only after confirmation; reserved values only in tests
and examples

**Scale/Scope**: one user, one machine, a handful of jobs, a few runs a day

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Schedules and secret references live in the private configuration; recorded streams are sanitized (fake ids, reserved paths) before commit; examples use reserved values | Pass |
| II. Read-only by construction | Headless runs get no shell and no tools (`--tools ""`, `--restricted`, `--safe-mode`, `dontAsk`); the restriction is checked from the start-up report, not trusted (R2). The only writes are local records, the outbox, logs and, after confirmation, the user's launchd jobs | Pass |
| III. Secrets | The configuration names keychain references only; values go to the child's environment only; a sentinel value is searched for in every output, log and record (SC-004) | Pass |
| IV. A human approves outward actions | Nothing leaves the machine but the model call the user's own Claude Code makes; installing jobs waits for a yes or a matching code (FR-029) | Pass |
| V. Configuration over code | Jobs, times, limits and secrets are configuration, validated by the schema; additive to version 1 | Pass |
| VI. Deterministic gathering | Period, key, lock, profile check and schema validation are code; one retry with the validator's message, then `inconclusive` (R3) | Pass |
| VII. Specified, tested, evaluated | Tests first, traced with `spec("007", …)`; no skill, so no eval suite | Pass |
| VIII. Ports and adapters | Five ports with fakes; each adapter has a current user (`check`); layers enforced by the existing import contract | Pass |
| IX. Observable runs | One record per start with trigger, job, engine and CLI versions, outcome, cost, duration, tools called, an agreement field | Pass |
| X. Standards; simplicity | launchd property lists, JSON, `platformdirs`, `keyring`; no daemon process yet (the gateway is chat-output) | Pass |

Re-checked after the design: still passes. The `fcntl` lock limits the file store to POSIX;
Windows has no user and no gate (ADR-0021), noted in R7.

## Project Structure

### Documentation (this feature)

```text
specs/007-daemon-core/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/commands.md, contracts/ports.md
├── checklists/requirements.md
└── tasks.md   (/speckit-tasks)
```

### Source Code (repository root)

```text
src/opscout/core/config.py           # Daemon, JobSettings; Configuration.daemon
src/opscout/core/daemon.py           # Job, RunProfile, StartupReport, RunResult, RunnerFacts,
                                     #   RunRecord, outcomes, ports (Protocols), CHECK job
src/opscout/services/daemon.py       # run_job(), compare_profile(), period/run key,
                                     #   wanted_plists(), render_status(), render_runs(),
                                     #   session_notices()
src/opscout/services/confirm.py      # confirmation_code(), moved from services/context.py
src/opscout/adapters/claude_cli.py   # ClaudeCliRunner: flags, stream parsing, environment
src/opscout/adapters/run_files.py    # FileRunStore (records, flock), LocalOutbox
src/opscout/adapters/keychain.py     # KeyringSecretStore
src/opscout/adapters/launchd.py      # LaunchdScheduler, Launchctl, plist bytes
src/opscout/entrypoints/daemon.py    # composition root: builds the adapters, engine command
src/opscout/entrypoints/hook.py      # session_start(): job notices after the SSO warning
src/opscout/entrypoints/cli.py       # run; daemon install|uninstall|status|runs; secret set|check
plugins/opscout/bin/opscout          # "could not run" wording (R10)
tests/unit/daemon/                   # test_config.py, test_jobs.py, test_run_job.py,
                                     #   test_runner.py, test_run_store.py, test_secrets.py,
                                     #   test_launchd.py, test_commands.py,
                                     #   test_session_notice.py, test_traceability.py,
                                     #   fakes.py, streams/*.jsonl, fake_claude.py
tests/unit/config_contract/compat/v1/daemon.yaml
docs/reference/configuration.md, docs/reference/daemon.md (new), example-config/config.yaml,
schemas/config.schema.json, pyproject.toml + uv.lock (two dependencies),
docs/adr/0016-engineering-baseline.md (macOS policy), docs/PLAN.md (§7, §8, §9),
specs/005-sso-check-hook/ (the "could not run" wording, R10)
```

**Structure Decision**: the existing single package and its layers (ADR-0011). Ports live in
`core` so `services` depends only on them; every adapter is built in
`entrypoints/daemon.py`, the only module that imports `adapters` for this feature, which the
existing layers contract already enforces (FR-025).

## Complexity Tracking

No violations to justify.
