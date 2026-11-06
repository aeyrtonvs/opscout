# Implementation Plan: Chat output

**Branch**: `feat/008-chat-output` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

## Summary

`daemon.chat` names Slack and the user's member id; two new keychain items hold the bot and
app-level tokens (R8). A `Chat` port, with `SlackChat` on `slack-sdk`'s `WebClient`, sends
the job's text as a direct message in a `markdown` block, with Agree and Disagree buttons
on results (R3). `ChatDelivery` wraps the outbox: it writes the file, then sends, retrying
for up to 10 minutes, and returns a receipt with the message reference; a missing token
fails the run before the model runs (R4, R8). A run that fails for another reason sends a
short notice (FR-024). `opscout gateway` holds a Socket Mode connection, installed by
`daemon install` as a kept-alive launchd entry; it acknowledges every envelope, acts only on
the configured user's clicks and reason dialogs, and writes the agreement into the run
record, then updates the message (R5, R6). Its state file feeds status and the
SessionStart notice (R7). The manifest ships in `deploy/slack/` with a two-scope test (R2).

## Technical Context

**Language/Version**: Python ≥ 3.13

**Primary Dependencies**: new at run time `slack-sdk` (R1): `WebClient` and the built-in
Socket Mode client, no extra; and `truststore` (R1), so TLS trusts the operating system's
certificates; existing `pydantic`, `platformdirs`, `keyring`

**Storage**: the run records (agreement and message reference added, version 1), the
outbox, `<data>/gateway.json`, `<data>/gateway.lock`; launchd property lists

**Testing**: pytest; a fake `Chat` and fake gateway events; the Slack adapter's payload
parsing and error mapping on hand-written payloads and a fake `WebClient`; the manifest
read by a test; a live check on the maintainer's workspace (R10)

**Target Platform**: macOS for the gateway's supervision (launchd); delivery and the
gateway command run on Linux too

**Project Type**: CLI and library (the engine), plus the plugin's existing hook

**Performance Goals**: a click stored within 5 s (SC-002); a reconnection within 1 minute
of the network's return (SC-006); delivery retries bounded at 10 minutes

**Constraints**: one recipient, DMs only; two bot scopes; no event subscription; tokens
never in a log, a record, an output or a model's environment; nothing from chat reaches a
model; install and uninstall only after confirmation

**Scale/Scope**: one user, one gateway, a few messages and clicks a day

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | The member id and tokens live in the private configuration and the keychain; examples and payload fixtures use `UEXAMPLE01`, `DEXAMPLE01` | Pass |
| II. Read-only by construction | The app's two scopes write DMs to its user and open them; no read scope, no event subscription; the gateway's only write is the run record and its own message | Pass |
| III. Secrets | Both tokens by keychain reference; resolved only in the delivery and gateway processes; slack-sdk loggers silenced; sentinel scans for tokens and reasons (SC-004) | Pass |
| IV. A human approves outward actions | The only outward action is the DM the user configured for themself; installing the gateway waits for a yes or a code | Pass |
| V. Configuration over code | Chat and its tokens are configuration, additive to version 1 | Pass |
| VI. Deterministic gathering | Rendering, retry, click handling and record updates are code; no model sees chat input | Pass |
| VII. Specified, tested, evaluated | Tests first, traced with `spec("008", …)`; no skill, so no eval | Pass |
| VIII. Ports and adapters | `Chat` and `Gateway` ports with fakes; `check` is their first user; adapters built only in the composition root (spec 007, FR-025) | Pass |
| IX. Observable runs | The agreement field is filled; the record keeps the message reference | Pass |
| X. Standards; simplicity | Slack's own SDK, no framework; launchd `KeepAlive`; JSON state file | Pass |

Re-checked after the design: still passes. `slack-sdk` is the one new dependency, with its
reason in R1.

## Project Structure

### Documentation (this feature)

```text
specs/008-chat-output/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/commands.md, contracts/ports.md
├── checklists/requirements.md
└── tasks.md   (/speckit-tasks)
```

### Source Code (repository root)

```text
src/opscout/core/config.py           # ChatSetting; Daemon.chat; KEYCHAIN_ITEMS; reserved "gateway"
src/opscout/core/chat.py             # ChatMessage, MessageRef, events, Chat and Gateway ports, errors
src/opscout/core/daemon.py           # Receipt, Agreement; Delivery.preflight; RunStore.get;
                                     #   RunRecord.chat and .agreement; ScheduledJob.keep_alive
src/opscout/services/chat.py         # render_message, ChatDelivery (retry), handle_event,
                                     #   agreement updates, gateway state rendering
src/opscout/services/daemon.py       # run_job: preflight, receipt, failure alert; wanted_jobs
                                     #   with the gateway; status and session lines
src/opscout/adapters/slack.py        # SlackChat, SlackGateway, read_request, error mapping
src/opscout/adapters/run_files.py    # LocalOutbox receipt; FileRunStore.get; gateway state file
src/opscout/adapters/launchd.py      # keep-alive property list
src/opscout/entrypoints/daemon.py    # wiring: chat delivery, alert, gateway command
src/opscout/entrypoints/cli.py       # opscout gateway
deploy/slack/opscout-app-manifest.yaml
tests/unit/chat/                     # test_config.py, test_manifest.py, test_render.py,
                                     #   test_delivery.py, test_gateway.py, test_slack.py,
                                     #   test_commands.py, test_traceability.py, fakes.py,
                                     #   payloads/*.json
tests/unit/daemon/                   # spec 007's tests, adjusted for the receipt and preflight
tests/unit/config_contract/compat/v1/chat.yaml
docs/reference/configuration.md, docs/reference/daemon.md (chat), example-config/config.yaml,
schemas/config.schema.json, pyproject.toml + uv.lock (one dependency),
docs/PLAN.md (status line, §7, §9)
```

**Structure Decision**: the existing package and layers. The chat port lives in `core`;
the retry, rendering and click handling in `services`, so they are tested with fakes; the
Slack adapter only maps between Slack and the neutral types, and only
`entrypoints/daemon.py` builds it (spec 007's forbidden contract already covers
`opscout.adapters`).

## Complexity Tracking

No violations to justify.
