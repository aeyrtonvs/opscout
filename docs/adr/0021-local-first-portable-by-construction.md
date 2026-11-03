---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Local-first and portable by construction; the foreseen hosted shape is a personal VM

## Context and Problem Statement

ADR-0006 runs phases 0–2 on the user's Mac and puts the scheduler behind an interface. Two
futures should stay cheap without being built now: other operating systems (Linux, Windows),
and moving the unattended parts to an always-on machine, because a laptop that is off sends
no daily and triages nothing (ADR-0006, consequences). The maintainer's hosted target is a
personal virtual machine, not serverless functions. Whether those futures stay cheap is
decided by the first lines of code: how jobs are scheduled, where credentials and run records
come from, how paths are built, and which language hooks are written in.

## Decision Drivers

- Principles VIII and X: only adapters with a current user are built; the smallest thing that
  satisfies the need.
- Another operating system or host should be a new adapter plus deployment notes, not a
  rewrite (ADR-0005).
- Every rule needs a gate (ADR-0018).
- A standing host that reads untrusted chat input must not weaken the read-only design
  (ADR-0010).

## Considered Options

- Write for macOS only; port when needed
- Portable by construction; build each adapter when it has a user
- Build Linux, Windows and VM support now
- Target serverless functions or a container platform for the unattended parts

## Decision Outcome

Chosen option: "portable by construction; build each adapter when it has a user", because the
rules below cost almost nothing at the start and are expensive to retrofit, while the adapters
themselves wait for a user (Principle VIII).

**Rules for all code, from Phase 0a.**

1. **Jobs are commands.** Each scheduled job is an idempotent CLI command
   (`opscout run <job>`). A scheduler adapter only installs, removes and triggers it. The
   daemon's only long-lived process is the chat gateway. A job records a run key for its
   period in the run store, so a retry or a double trigger does not send a second message.
2. **Host-specific capabilities sit behind ports**, each with a fake for tests:
   - `Scheduler` (ADR-0006): the launchd adapter now.
   - `Runner` (ADR-0012): unchanged.
   - `SecretStore`: resolves a secret from the name the configuration gives (ADR-0014). The
     adapter now is `keyring`, which uses the macOS keychain and also supports the Windows
     Credential Locker and the Secret Service of Linux desktops.
   - `RunStore`: run records (Principle IX). The adapter now writes local files.
   - The daily's Claude Code session-history source is an adapter of its own, local-only by
     nature. What the daily does where it is missing is decided in the daily-standup spec.
3. **No host assumptions in code.** Paths use `pathlib`; the configuration is resolved as
   ADR-0014 says; state, logs and caches live under `platformdirs` directories; executables
   such as `claude` are found with `shutil.which` or set in the configuration; text is read
   and written as UTF-8 explicitly. No hard-coded `~/Library`, `/usr/local` or `/bin/bash`.
4. **Hooks and helper scripts are Python**, run through uv (for example
   `opscout hook sso-check`). This covers the plugin's hooks and this repository's
   development hooks alike. No shell scripts.
5. **One artifact for every host.** The package installs and runs with uv alone, so the same
   release serves a laptop and a VM.

**Gates** (ADR-0018):

- ruff enables `PTH` (flake8-use-pathlib).
- import-linter: besides the layers of ADR-0011, platform adapters (launchd, keyring) are
  imported only by the composition root in `entrypoints`.
- CI runs the whole suite on Linux (ADR-0016), so a macOS-only assumption fails there.
- The daemon-core spec includes a test: a job triggered twice for the same period delivers
  once.
- Windows has no gate yet. A Windows CI job arrives with the first Windows user, together
  with the Task Scheduler adapter.

**The foreseen hosted shape: a personal VM.** It is not built now. When the run-log evidence
of Phase 3 justifies it, a new ADR supersedes the hosting part of ADR-0006 and starts from
this list:

- **What moves:** the chat gateway and the headless triage runs. Interactive skills stay in
  the user's Claude Code, and the daily stays on the laptop, where the session history is.
- **Deployable:** the same package installed with uv, plus systemd units, through the same
  `Scheduler` adapter a Linux desktop uses. No container is needed; if one is ever wanted, it
  is built from the same `uv.lock` (ADR-0020).
- **Secrets:** a headless `SecretStore` adapter, for example systemd credentials or the cloud
  provider's secret manager. Principle III names the OS keychain, so the constitution is
  amended to cover it.
- **Two identities:** a runtime identity that reads only the harness's own secrets, and the
  read-only investigation identity of ADR-0010, which keeps denying secret-value APIs.
- **Claude authentication on a server:** re-check the usage policy, then use a
  `claude setup-token` token or an API key (`AgentSdkRunner`), passed only to the child
  process (ADR-0012).
- **Host posture:** no inbound ports (Socket Mode connects outward), patched, administrative
  access restricted, and a threat model for a standing host that reads untrusted chat input.
- **Run records** stay on the VM's disk, so Principle IX holds; run-insights reads the records
  of both hosts.
- **First,** re-check Anthropic's hosted options (PLAN.md §8), ruled out on 2026-11-02 for
  reasons that change quickly.

Not a target: serverless functions, because Socket Mode keeps a stateful WebSocket connection
open and needs a long-lived process; and team-wide services, which stay out of this
repository (ADR-0006).

### Consequences

- Good, because Linux, Windows and a VM each become an adapter plus deployment notes, not a
  rewrite.
- Good, because the ports double as test seams; their fakes are needed anyway.
- Good, because idempotent job commands also cover the laptop's own edge cases: catch-up
  after sleep and manual reruns.
- Bad, because it adds two small runtime dependencies, `platformdirs` and `keyring`; this ADR
  is their justification.
- Bad, because Windows compatibility stays unverified until a Windows CI job exists, so
  regressions can accumulate unseen.
- Neutral: the VM still needs its own ADR, a threat model and a constitution amendment; this
  ADR only keeps that path cheap.

### Confirmation

- `pyproject.toml` enables ruff `PTH`; the import-linter contracts include the
  composition-root rule; CI runs on Linux.
- The pull request template asks whether new host-specific code sits behind a port.
- The daemon-core spec carries the "triggered twice, delivered once" test.

## More Information

Related: ADR-0005, ADR-0006 (complemented, not superseded), ADR-0010, ADR-0011, ADR-0012,
ADR-0014, ADR-0016, ADR-0018, ADR-0020.

The constitution says "OS-specific code lives behind the scheduler port", while ADR-0011
already lists the keychain as an adapter of its own. A PATCH amendment that reads "behind
ports (scheduler, secret store)" removes the mismatch; it is tracked in PLAN.md §9.

Checked 2026-11-03:

- `keyring` 25.7.0 (PyPI): its recommended backends are the macOS Keychain, the freedesktop
  Secret Service, KWallet and the Windows Credential Locker.
- `platformdirs` 4.14.3 (PyPI).
- Slack, "Using Socket Mode" (docs.slack.dev): events arrive over a WebSocket URL created at
  runtime, with no public HTTP Request URL; WebSockets are "a bidirectional stateful
  protocol".
- ruff's rule set "flake8-use-pathlib (PTH)" (docs.astral.sh/ruff/rules).
