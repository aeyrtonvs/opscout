---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Spec-Driven Development with GitHub Spec Kit

## Context and Problem Statement

Most of the code will be written with a coding agent, and the product itself is agents whose
behavior is defined in prose (skills). Without an explicit, reviewable statement of what each
feature must do, output is judged against intent that exists only in someone's head, and agent
behavior cannot be tested. The project is also a portfolio, so how it is built should be
legible.

## Decision Drivers

- Intent is reviewed before code, and requirements are testable.
- Works natively in Claude Code without tying the repository to one agent or editor.
- Artifacts are plain Markdown in the repository.
- Overhead proportional to the size of the change (one maintainer).

## Considered Options

- GitHub Spec Kit
- OpenSpec
- Kiro
- BMAD Method
- No framework (plans in PLAN.md and pull request descriptions)

## Decision Outcome

Chosen option: "GitHub Spec Kit", used **spec-anchored**: each feature gets
`specs/NNN-slug/` (spec, plan, research, contracts, tasks), and the spec stays the reference for
that feature after merge. Code is not regenerated from specs.

Setup (2026-11-03): Spec Kit 1.2.6; `claude` integration, which installs skills in
`.claude/skills/speckit-*`; `sh` scripts; the official `git` extension with branch prefix
`feat/` and Conventional Commit messages.

No community extensions are installed: they run prompts and scripts with the developer's
permissions, so each one needs a review and a pinned version first. Candidates to evaluate:
ADR and spec cross-checks, CI spec gates, requirement-to-test traceability, threat modeling.

A spec is required for new features and for changes to specified behavior. Fixes, chores and
documentation go through a plain pull request.

### Consequences

- Good, because intent is reviewed before implementation, and acceptance scenarios become the
  eval cases for agent behavior (ADR-0013).
- Good, because Spec Kit is open source (MIT), works with many coding agents, and is the most
  widely adopted SDD toolkit.
- Bad, because each feature produces several Markdown files to review. Mitigation: short specs,
  `/speckit-clarify` before planning, `/speckit-analyze` before implementing, no spec for small
  changes.
- Bad, because Spec Kit changes quickly (releases every few days). Mitigation: the version is
  pinned in `.specify/init-options.json`, and upgrades go through
  `specify integration upgrade` with a reviewed diff.

### Confirmation

Every feature pull request links its `specs/NNN-slug/`; its `plan.md` has a passing
Constitution Check; `/speckit-analyze` reports no critical findings before implementation.

## Pros and Cons of the Options

- **OpenSpec**: lighter and change-centric, strongest when evolving an existing system. This
  repository is greenfield, where Spec Kit's full cycle pays off.
- **Kiro**: spec-native, but it is an IDE, so the workflow would depend on one editor.
- **BMAD Method**: a multi-persona agile process, heavy for one maintainer.
- **No framework**: no overhead, but no traceability from intent to tests.
