# Implementation Plan: Ship skill

**Branch**: `feat/004-ship-skill` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

## Summary

The configuration gains an optional `ship` section. The engine gains the conventions
command, the branch and message checks, and the push guard: a pure decision over a plain
`git push` (R2), run by a PreToolUse hook the plugin ships with `onFailure: block` (R1). The
plugin gains the `ship` skill. The eval runner gains scratch repositories and `tool_order`.

## Technical Context

**Language/Version**: Python ≥ 3.13; Markdown (skill, cases); JSON (`hooks/hooks.json`)

**Primary Dependencies**: none new; git and the user's `gh`

**Testing**: pytest (models, checks, guard decisions, hook I/O with scratch git repos);
the headless eval runner

**Performance Goals**: guard decision under 1 s, start-up included (SC-004)

**Constraints**: the guard never fails open; nothing pushes outside the machine in tests or
evals; reserved values only

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Defaults and test repositories are generic | Pass |
| II. Read-only by construction | The guard is a mechanism, not a prompt; the skill never merges or rewrites history | Pass |
| III. Secrets | The skill never prints staged secret values; `gh` keeps its own token | Pass |
| IV. A human approves outward actions | Every push and pull request is asked; protected branches are denied | Pass |
| V. Configuration over code | Conventions come from `ship`, with defaults | Pass |
| VI. Deterministic gathering | Checks and the guard are typed, tested code | Pass |
| VII. Specified, tested, evaluated | Tests first; an eval suite with `tool_order` | Pass |
| VIII. Ports and adapters | Pure decisions in services; git calls in entrypoints; GitHub through the user's `gh`, no adapter yet | Pass |
| IX. Observable runs | No unattended run | Not applicable |
| X. Standards; simplicity | Conventional Commits, PreToolUse hooks; the plain form only | Pass |

## Project Structure

```text
src/opscout/core/config.py        # Ship, PullRequestConventions
src/opscout/core/ship.py          # defaults, PushDecision
src/opscout/services/ship.py      # check_branch(), check_message(), render_rules(), decide_push()
src/opscout/entrypoints/cli.py    # ship rules | check-branch | check-message; hook pre-tool-use
src/opscout/entrypoints/hook.py   # reads the event, asks git for the branches, prints the decision
plugins/opscout/hooks/hooks.json  # the PreToolUse guard
plugins/opscout/skills/ship/SKILL.md
plugins/opscout/evals/004-*/      # cases with scaffold.py
tools/skill_evals.py              # scaffold.py, tool_order
tests/unit/ship/test_ship.py, tests/tools/test_skill_evals.py
docs/reference/configuration.md, example-config/config.yaml, schemas/config.schema.json
```

## Complexity Tracking

No violations to justify.
