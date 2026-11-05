# Implementation Plan: SSO check hook

**Branch**: `feat/005-sso-check-hook` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

## Summary

The configuration gains an optional `sso` section. The engine gains a pure SSO check: it
finds the SSO sessions in an AWS config's text and judges each cached token by its expiry
(R2, R3). The entrypoints read the two kinds of file with a size limit and nothing else
(R4), and add `opscout sso check` and `opscout hook session-start`. The plugin's
`hooks/hooks.json` gains a SessionStart hook that runs the latter through the launcher (R1).

## Technical Context

**Language/Version**: Python ≥ 3.13; JSON (`hooks/hooks.json`)

**Primary Dependencies**: none new (`configparser`, `hashlib`, `json`, `datetime` from the
standard library)

**Testing**: pytest, with an AWS config and a token cache built in a temporary home

**Performance Goals**: the check's 95th percentile under 100 ms; the whole hook, start-up
included, under 1 s (SC-003)

**Constraints**: no network, no other program, no writes; only an expiry and whether a token
is present are taken from a cache file; the hook never blocks a session start; reserved
values only in tests and examples

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Session names appear only in the user's own session; tests use `example-session` and `https://example.com/start` | Pass |
| II. Read-only by construction | The check opens two kinds of file for reading; it has no code path that writes, logs in or calls out | Pass |
| III. Secrets | A cache file is parsed in memory, and only `expiresAt` and the presence of `accessToken` are kept; no token, secret or other value is printed, logged, stored or returned (R4) | Pass |
| IV. A human approves outward actions | Nothing leaves the machine; logging in stays the user's command | Pass |
| V. Configuration over code | Which sessions, and on or off, come from `sso`, with defaults | Pass |
| VI. Deterministic gathering | The check is typed, tested code; no model involved | Pass |
| VII. Specified, tested, evaluated | Tests first; no skill, so no eval suite (ADR-0013 covers skills) | Pass |
| VIII. Ports and adapters | Pure finding and judging in services; file reading in entrypoints, like the configuration loader; no port, since reading local files is not a host capability that varies (ADR-0021 lists the ports) | Pass |
| IX. Observable runs | No unattended run | Not applicable |
| X. Standards; simplicity | A SessionStart hook; the AWS CLI's own cache layout; no dependency | Pass |

## Project Structure

```text
src/opscout/core/config.py        # Sso; Configuration.sso
src/opscout/core/sso.py           # SsoSession, SessionState, SessionCheck, limits
src/opscout/services/sso.py       # find_sessions(), select(), cache_key(), judge(), render_*()
src/opscout/entrypoints/sso.py    # reads the AWS config and the cache files; check_sessions()
src/opscout/entrypoints/hook.py   # session_start()
src/opscout/entrypoints/cli.py    # sso check; hook session-start
plugins/opscout/hooks/hooks.json  # the SessionStart hook
tests/unit/sso/test_sso.py
tests/unit/config_contract/compat/v1/sso.yaml
docs/reference/configuration.md, example-config/config.yaml, schemas/config.schema.json
plugins/opscout/README.md, AGENTS.md (repository map), docs/PLAN.md (§7 note, §9)
```

## Complexity Tracking

No violations to justify.
