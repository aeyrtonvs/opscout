---
paths:
  - "specs/**"
---

# Feature specs (Spec Kit)

- The flow is `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-analyze` → `/speckit-implement`, then `/speckit-converge` and an independent
  review of the diff in a fresh context (ADR-0008, ADR-0018).
- Every spec has a **Non-Goals** section. For an agent-facing feature, it lists what the
  agent must never do.
- Acceptance scenarios are testable, and IDs carry forward (PLAN.md §4.2): tasks cite
  stories and requirements (`T012 [US1] … FR-003`), tests carry
  `@pytest.mark.spec("NNN", "FR-00X")`, and eval cases are named after scenarios
  (`NNN-us1-s2`).
- Tests are mandatory and come first, whatever the Spec Kit tasks template says.
- Examples use reserved, fake values only: `123456789012`, `example-prod`,
  `#alerts-example`.
- The spec stays the reference after merge. A change in specified behavior updates it in
  the same pull request.
- Progress goes in the feature's `tasks.md`; new open questions go in `docs/PLAN.md` §9.
