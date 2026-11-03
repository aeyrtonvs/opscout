---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Integrations behind adapter interfaces; only used adapters are built

## Context and Problem Statement

The harness talks to alert sources, cost data, a code host, a ticket system and a chat
platform. The maintainer's environment uses one provider for each.

## Decision Outcome

Adapter interfaces for alerts, costs, code host, tickets and chat. Implemented: AWS, Datadog,
Bitbucket, Jira, Slack.

Rationale as recorded: shows design; no unused integrations.

### Consequences

- Good, because another provider is a new adapter, not a change to the core.
- Bad, because an interface designed from a single implementation may need revision when the
  second one arrives; that revision happens with the second adapter.

### Confirmation

Import contracts keep the core free of adapter imports (ADR-0011); each port has contract
tests that every adapter must pass.

## More Information

Migrated unchanged from PLAN.md §3.
