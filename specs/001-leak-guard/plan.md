# Implementation Plan: Leak guard

**Branch**: `feat/001-leak-guard` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-leak-guard/spec.md`

## Summary

The leak check exists (Phase 0a, ADR-0015). This feature makes it a specified, traced
gate: every test is tied to a requirement, a traceability test fails when a requirement has
no test, and the missing cases are added. One behavior is new: before a push, the check
also examines the names of the branches and tags being pushed (FR-032), within what
pre-commit lets a pre-push hook see ([research.md](research.md) R1). The deny-list file name
is git-ignored so it cannot be committed by mistake (FR-012), and the rule that a pattern
changes only on evidence is written down (FR-027).

## Technical Context

**Language/Version**: Python ≥ 3.13 (CI also runs 3.15)

**Primary Dependencies**: the standard library only (`re`, `ipaddress`, `tomllib`,
`argparse`, `subprocess`); the git CLI; pre-commit runs the hooks. No new dependency.

**Storage**: none; reads `tools/leak_allowlist.toml` and the private
`<config dir>/leak-denylist.txt`

**Testing**: pytest, with scratch git repositories from `tests/tools/conftest.py`

**Target Platform**: macOS and Linux developer machines and GitHub-hosted runners

**Project Type**: repository development tooling (`tools/`), not shipped in the package
or the plugin

**Performance Goals**: under 1 s end to end on a typical change of 20 files and 1,000
lines; linear time on pathological lines

**Constraints**: offline; no deny-list term in the repository or in CI logs; the test file
itself must pass the check

**Scale/Scope**: one module (≈500 lines) and its test module; about 30 requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Synthetic leaks are assembled at run time; the deny-list stays in the private config and is git-ignored here; CI output is redacted | Pass |
| II. Read-only by construction | The check only reads files and git; it never changes them | Pass |
| III. Secrets: existence, never value | Secrets stay gitleaks' job (Non-Goals); findings never print a deny-list term in CI, which does not run layer 2 | Pass |
| IV. A human approves outward actions | The check runs before a push; it pushes nothing. The rule-5 `ask` prompt is unchanged | Pass |
| V. Configuration over code | Organization terms come only from the private deny-list; no organization-specific branch in code | Pass |
| VI. Deterministic gathering | All of it is typed, tested code; no model involved | Pass |
| VII. Specified, tested, evaluated | Tests first and tied to FRs; no agent behavior, so no eval suite | Pass |
| VIII. Ports and adapters | `tools/` is development tooling outside the `opscout` package and its layers | Not applicable |
| IX. Observable runs | No agent run | Not applicable |
| X. Standards; simplicity | pre-commit, git, TOML; the smallest change that meets FR-032 (R1) | Pass |

Post-design re-check: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/001-leak-guard/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R5
├── data-model.md
├── quickstart.md
├── contracts/cli.md     # modes, inputs, output, exit status
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
tools/
├── leak_check.py          # ref-name check in `pushed` mode; docstring states FR-027
├── _git.py                # local ref names (for-each-ref)
└── leak_allowlist.toml    # unchanged unless a real false positive appears

tests/tools/
└── test_leak_check.py     # spec markers on every test, new cases, traceability and timing tests

.gitignore                 # leak-denylist.txt
CONTRIBUTING.md            # ref names are checked; pattern changes need a synthetic case
docs/PLAN.md               # Phase 0b progress; §9 records the no-new-commit push limit
```

**Structure Decision**: the feature stays where Phase 0a put the leak check, in `tools/`
(not shipped) with its tests in `tests/tools/`. No new module.

## Design notes

- **Ref names (FR-032)**: `pushed` mode adds a scan of the names in R1 after the commit
  scan. Names are deduplicated, stripped of `refs/heads/` and `refs/tags/`, and scanned with
  `scan_line`, so the allow-list and the deny-list apply as everywhere else.
- **Traceability (FR-030)**: a test parses `FR-0NN` IDs from `spec.md` and compares them
  with the `spec("001", …)` markers on the module's tests (R3).
- **Timing (FR-031)**: a subprocess with `sys.executable` runs `files` on 20 generated files
  of 50 lines each and must finish in under one second (R2).

## Complexity Tracking

No violations to justify.
