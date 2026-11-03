---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# The project is named opscout; the working name ops-harness is retired

## Context and Problem Statement

The working name `ops-harness` described the project, but checks on 2026-11-03 found two
collisions:

- On PyPI, `ops-harness` is taken by an unrelated project from the ecosystem of Canonical's
  Python `ops` framework, where "Harness" is the name of its charm-testing tool. A package
  with this name could not be published, and Python users would confuse it with that tool.
- "Harness" is also the name of a large CI/CD vendor that sells cloud cost management, which
  overlaps need #2.

A name is cheap to change only before the first push and the first release.

## Decision Drivers

- One name everywhere: repository, Python distribution and import, CLI, plugin, marketplace.
- The name says what the agents do: investigate and report, never act.
- Free on PyPI and GitHub, with no product of the same name in the space.
- Short enough for a CLI.

## Considered Options

- Keep `ops-harness` for the repository, with another distribution name
- `toil-harness`
- `toilkit`
- `opscout`

## Decision Outcome

Chosen option: "opscout", *ops* plus *scout*. A scout goes ahead, investigates and reports with
evidence, and does not engage, which is exactly the read-only contract (Principle II). On
2026-11-03 the name was free on PyPI, GitHub had only one unrelated repository with it (no
stars), and no product with that name turned up. The category stays in the tagline:
**"opscout — a read-only agent harness for DevOps toil"**.

| Identifier | Value |
|---|---|
| Repository | `github.com/aeyrtonvs/opscout` |
| Python distribution and import package | `opscout` |
| CLI | `opscout` |
| Plugin and marketplace | `opscout` (`/plugin install opscout@opscout`) |
| Plugin directory | `plugins/opscout/` |
| Config environment variable | `OPSCOUT_CONFIG` |
| Default config directory | `~/.config/opscout/` |
| Private configuration repository (suggested) | `opscout-config` |

### Consequences

- Good, because the name is distinctive, searchable and identical across every channel.
- Bad, because the name no longer contains "harness", the term the agent community uses for
  this kind of system. The tagline, the description and the repository topics carry it.
- Neutral: local clones may keep their old folder names; nothing in the engine depends on them.

### Confirmation

Availability on PyPI and GitHub is re-checked right before the first push and the first
release.

## Pros and Cons of the Options

- **Keep ops-harness, publish under another name**: no rename work, but two names for one
  thing, and both collisions stay.
- **toil-harness**: keeps "harness" and uses the SRE term for repetitive work, but it is long
  for a CLI, and Toil is also an established Python workflow engine.
- **toilkit**: short, with a pun on "toolkit", but it reads as a collection of scripts rather
  than agents.

## More Information

The documents written before this decision were updated editorially on the same day. Their
decisions are unchanged.
