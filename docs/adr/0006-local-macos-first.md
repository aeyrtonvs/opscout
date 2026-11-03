---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Run locally, macOS first; team-wide automation stays out of this repository

## Context and Problem Statement

The harness needs the user's local session history, cloud credentials and keychain. Hosted
options were checked against the official documentation on 2026-11-02 (PLAN.md §8).

## Decision Outcome

- Phases 0–2 run on the user's machine.
- macOS first (launchd). The scheduler sits behind an interface, so systemd is one more
  adapter.
- The team-wide automatic phase is out of this repository: it belongs in the employer's own
  agent service, without depending on this personal repository.

Rationale as recorded: Claude in Slack for teams is Team/Enterprise only and runs in a cloud
sandbox without the user's cloud credentials; Claude Code in Slack works with GitHub
repositories only; cloud routines cannot read local files such as the session history the
daily needs. For the team-wide phase: ownership and supply chain.

### Consequences

- Good, because credentials and history never leave the machine, and there is nothing to host.
- Bad, because no daily is sent when the machine is off (launchd runs a missed calendar job on
  wake).
- Bad, because Linux users wait for the systemd adapter.

### Confirmation

No hosted component appears in any spec before an ADR supersedes this one.

## More Information

Migrated unchanged from PLAN.md §3 (rows "OS", "Where it runs" and "Team-wide automatic
phase").
