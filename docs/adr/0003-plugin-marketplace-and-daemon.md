---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Distribute as a Claude Code plugin from a self-hosted marketplace, plus a separate daemon

## Context and Problem Statement

Skills, subagents and hooks need a native, versioned way to be shared and updated. The
scheduler and the chat gateway must run when no Claude Code session is open.

## Decision Outcome

The repository is its own marketplace: `.claude-plugin/marketplace.json` at the root lists the
plugin at `./plugins/opscout`. Users install it with
`/plugin marketplace add <owner>/<repo>` and `/plugin install opscout@<marketplace>`.
The daemon lives outside Claude Code and has its own installer.

Rationale as recorded: the native way to share skills, with versioned updates; the daemon
lives outside Claude Code.

### Consequences

- Good, because skills install and update natively and carry a version.
- Bad, because there are two artifacts; they are released in lockstep (ADR-0016).
- Neutral: auto-update is off by default for third-party marketplaces, so users update with
  `claude plugin update` (checked 2026-11-03).

### Confirmation

`claude plugin validate --strict` passes in CI for the marketplace and the plugin.

## More Information

Migrated unchanged from PLAN.md §3; the paths and commands were added from the plugin
documentation checked on 2026-11-03.
