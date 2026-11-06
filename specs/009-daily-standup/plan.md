# Implementation Plan: Daily standup

**Branch**: `feat/009-daily-standup` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

## Summary

A `standup` section names the user's projects (local paths, Bitbucket repositories), their
commit identities and their Bitbucket login; a new keychain item holds the token (R10).
Three ports gather the window's facts in code: Claude Code transcripts (only the user's own
prompts, with pasted and tagged blocks removed, R1), `git log` on local clones (R2), and
Bitbucket Cloud's pull requests and review states (R3). The services compute the window
(R4), minimize (R5), redact (R6), mark blockers (R3, FR-021), number the facts, build a
prompt with the facts as an untrusted block, and validate the model's output against them
with pydantic validation context, so a wrong citation goes through spec 007's retry (R7).
Spec 007's `run_job` gains a `prepare` step after its idempotency check, and a quiet window
is delivered without a model run (R8). `opscout standup preview` shows exactly what would
be sent (FR-022). Synthetic evaluations run with a fake runner in the suite and with the
user's model on demand (R9).

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: none new: stdlib `urllib`, `subprocess`, `json`, `re`; `truststore`
and the existing spec 007 and 008 machinery

**Storage**: none new; run records hold references only (FR-013)

**Testing**: pytest; fakes for the three ports; hand-written transcript and Bitbucket samples
that follow the documented shapes; a real temporary git repository; a redaction corpus;
evaluation cases run with a fake runner, and with the user's model on demand

**Target Platform**: macOS and Linux (the sources are files, git and HTTPS)

**Project Type**: CLI and library (the engine)

**Performance Goals**: a daily within 3 minutes and 0.10 USD (SC-006); the preview within
seconds

**Constraints**: read-only sources; only redacted, minimized facts reach the model, and only
the summary reaches the user; no reply or tool output from transcripts; no new dependency

**Scale/Scope**: one user, a few projects, a few dozen facts a day

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Projects, identities, logins, deny-list terms live in the private configuration; samples and evaluations use `example-*` values | Pass |
| II. Read-only by construction | Transcripts and clones read; git read commands only; a read-scoped token; the model run has no tools | Pass |
| III. Secrets | The token by keychain reference, only in the adapter; redaction of secrets and personal data before the model, tested on a corpus; references only in the record | Pass |
| IV. A human approves outward actions | Nothing new leaves: the summary goes to the user's own model and DM; scheduling waits for confirmation (spec 007) | Pass |
| V. Configuration over code | Projects, sources, limits and the deny-list are configuration | Pass |
| VI. Deterministic gathering | Facts, window, blockers and checks are code; the model only words cited facts, and wrong citations are refused | Pass |
| VII. Specified, tested, evaluated | Tests first; an evaluation suite on synthetic histories with code graders (ADR-0013) | Pass |
| VIII. Ports and adapters | Three ports with fakes; `standup` is their first user | Pass |
| IX. Observable runs | The record lists the inputs by reference and the redactions; agreement from spec 008 | Pass |
| X. Standards; simplicity | No new dependency; JSON Lines, git, REST | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/009-daily-standup/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/commands.md, contracts/ports.md
├── checklists/requirements.md
└── tasks.md   (/speckit-tasks)
```

### Source Code (repository root)

```text
src/opscout/core/config.py            # Standup section; JOB_NAMES, KEYCHAIN_ITEMS
src/opscout/core/standup.py           # Window, Fact, Gathered, StandupOutput, ports, SourceError
src/opscout/core/daemon.py            # RunProfile.validation_context, Start.prepare, Preparation
src/opscout/services/standup.py       # window, gather, minimize, blockers, prompt, render, preview
src/opscout/services/redact.py        # redaction rules (R6)
src/opscout/services/daemon.py        # run_job calls prepare
src/opscout/adapters/claude_transcripts.py
src/opscout/adapters/git_log.py
src/opscout/adapters/bitbucket.py
src/opscout/adapters/claude_cli.py    # pass the validation context
src/opscout/entrypoints/daemon.py     # wiring; the standup job's prepare; preview command
src/opscout/entrypoints/cli.py        # opscout standup preview
tools/standup_evals.py
evals/standup/<case>/                  # synthetic histories and expected checks
tests/unit/standup/                   # test_config, test_window, test_transcripts, test_git,
                                      #   test_bitbucket, test_redact, test_gather, test_output,
                                      #   test_job, test_preview, test_evals, test_traceability,
                                      #   fakes.py, samples/
docs/reference/standup.md, docs/reference/configuration.md, example-config/config.yaml,
schemas/config.schema.json, docs/PLAN.md
```

**Structure Decision**: the existing layers. Gathering is behind ports so the services are
pure and tested with fakes; the adapters only read their source and map it.

## Complexity Tracking

No violations to justify.
