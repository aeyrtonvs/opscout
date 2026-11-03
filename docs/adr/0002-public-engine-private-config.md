---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Public engine, private configuration repository

## Context and Problem Statement

The engine is a public portfolio project and is also used at work. Work use needs real
organizational facts (accounts, alert formats, channels) that must never become public.

## Decision Outcome

The engine is public. All organization-specific configuration lives in a separate
**private** repository, which the engine reads from a path or an environment variable.
`example-config/` in this repository is the template, with fake values.

Rationale as recorded: clone plus your own config; no data can leak by accident because the
repositories are separate.

### Consequences

- Good, because leaking data takes two mistakes (writing it into the wrong repository and
  getting past the leak check), not one `git add -f`.
- Good, because anyone can clone the engine and bring their own configuration.
- Bad, because two repositories must stay compatible; handled by the versioned
  configuration schema (ADR-0014).

### Confirmation

Leak check in pre-commit and CI (ADR-0015); `example-config/` validated in CI.

## More Information

Migrated unchanged from PLAN.md §3. Alternatives were not recorded at the time.
