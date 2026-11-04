# Implementation Plan: Summary skill

**Branch**: `feat/003-summary-skill` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-summary-skill/spec.md`

## Summary

Three parts. The configuration gains an optional `writeups` section (additive; version 1).
The engine gains `opscout writeup formats`, which prints the built-in formats with the
configured ones applied and always exits 0. The plugin gains its first code: a `bin/opscout`
launcher, run through uv, that runs the engine from the clone or the matching release
(ADR-0022), and a `summary` skill that injects the formats and writes one block of text.
An eval suite traced to the scenarios proves the skill against a no-plugin baseline.

## Technical Context

**Language/Version**: Python ≥ 3.13 (engine and launcher); Markdown (skill, eval cases)

**Primary Dependencies**: none new; Pydantic and PyYAML from spec 002; uv runs the launcher;
`claude plugin eval` (Claude Code 2.1.318) runs the evals

**Storage**: none

**Testing**: pytest for the models, the formats command, the launcher and the skill's
frontmatter; `claude plugin eval` for the skill's behavior

**Target Platform**: macOS and Linux; Claude Code with the plugin loaded from a clone
(`--plugin-dir`) until the first release

**Project Type**: the `opscout` package plus the plugin (`plugins/opscout/`)

**Performance Goals**: printing the formats under 2 s from a clone (SC-004)

**Constraints**: the skill pre-approves only the formats command; evals use synthetic data,
`--no-publish`, a USD 3 ceiling and the maintainer's confirmation for each run

**Scale/Scope**: two small modules, one CLI command, one launcher, one skill, about ten eval
cases; 29 requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Public engine, private data | Built-in formats are generic (FR-007); eval sessions are synthetic; evals never read the real configuration; reports stay local | Pass |
| II. Read-only by construction | The skill only writes text in the reply; its only tool is the pre-approved formats command (FR-019) | Pass |
| III. Secrets | The write-up never holds a secret value (FR-016); an eval case baits it | Pass |
| IV. A human approves outward actions | Nothing is posted; every eval run is confirmed and unpublished; no release is cut | Pass |
| V. Configuration over code | Formats come from the configuration, with built-in defaults; no organization branch | Pass |
| VI. Deterministic gathering | The engine resolves and prints the formats in tested code; the model only writes | Pass |
| VII. Specified, tested, evaluated | Tests first; an eval suite traced to the scenarios, above the baseline (ADR-0013) | Pass |
| VIII. Ports and adapters | Models in core, resolution and rendering in services, CLI in entrypoints | Pass |
| IX. Observable runs | No unattended run; the run log arrives with daemon-core | Not applicable |
| X. Standards; simplicity | Agent Skills format, uv, PyPI; the launcher is one file | Pass |

The launcher is a cross-cutting decision, recorded as ADR-0022.

Post-design re-check: unchanged, all pass.

## Project Structure

### Documentation (this feature)

```text
specs/003-summary-skill/
├── spec.md
├── plan.md                       # this file
├── research.md                   # R1–R6
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── writeup-formats.md        # the command and its output
│   └── launcher.md               # bin/opscout
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/opscout/
├── core/config.py                # Writeups and WriteupFormat in Configuration
├── core/writeups.py              # BUILT_IN_FORMATS, SHARED_RULES
├── services/writeups.py          # resolve_formats(), render_formats()
└── entrypoints/cli.py            # `writeup formats [--config DIR]`

plugins/opscout/
├── bin/opscout                   # the launcher (ADR-0022)
├── skills/summary/SKILL.md       # the skill
├── evals/003-us1-s1/ …           # one case per scenario
└── README.md                     # uv is required; loading from a clone

tests/unit/
├── writeups/test_writeups.py     # models, resolution, rendering, command, launcher, skill
└── config_contract/compat/v1/writeups.yaml

schemas/config.schema.json        # regenerated
example-config/config.yaml        # a commented writeups example
docs/adr/0022-plugin-runs-the-engine-through-uv.md, docs/adr/README.md
docs/reference/configuration.md   # the writeups section
docs/PLAN.md, AGENTS.md           # progress; §9 item on how the plugin finds the package
```

**Structure Decision**: the engine parts follow ADR-0011's layers; the plugin parts follow
ADR-0003's layout. Tests go in `tests/unit/writeups/` (a directory name no `.gitignore`
rule matches; the sensor of spec 002's fix checks it).

## Complexity Tracking

No violations to justify.
