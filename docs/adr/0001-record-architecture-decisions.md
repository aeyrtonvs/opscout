---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Record architecture decisions as MADR files

## Context and Problem Statement

Decisions lived in a table in `docs/PLAN.md` §3: the choice and a one-line reason. The table
does not keep the options that were rejected, the consequences that were accepted, or how
compliance is checked. Spec Kit records decisions per feature (`research.md`), but decisions
that cross features need their own place.

## Decision Drivers

- A reader who was not there (reviewer, contributor, coding agent) can follow the reasoning.
- Low ceremony for a single maintainer.
- A widely recognized format.

## Considered Options

- Keep the table in PLAN.md
- Nygard-style ADRs
- MADR 4.0

## Decision Outcome

Chosen option: "MADR 4.0", because it is the most used structured ADR format, has a minimal
variant, and keeps options and consequences next to the decision. PLAN.md §3 becomes an index
of the ADRs.

Rules:

- One decision per file, `NNNN-title-as-decision.md`, from `template.md`.
- Lifecycle: `proposed` → `accepted` | `rejected`; later `deprecated` or
  `superseded by ADR-NNNN`. An accepted ADR is not rewritten; a change is a new ADR.
- An ADR is needed when a decision is hard to reverse, affects more than one feature, or
  changes how the constitution is applied. Feature-local decisions stay in the feature's
  `research.md`.

### Consequences

- Good, because every decision states its alternatives and how it is confirmed.
- Good, because agents can load only the ADRs relevant to a task.
- Bad, because there are more files to keep current; mitigated by the slim template.

### Confirmation

The pull request template asks whether an ADR is needed; `docs/adr/README.md` lists every ADR
with its status.

## More Information

ADRs 0002–0007 are decisions already recorded in PLAN.md §3, migrated without change.
