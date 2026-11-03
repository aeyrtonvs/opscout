---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# Documentation as code: Diátaxis, Zensical, Mermaid

## Context and Problem Statement

The documentation has three audiences: users (install, configure), contributors (add a skill
or an adapter) and reviewers (why it is built this way). Material for MkDocs, the usual choice
for Python projects, is in maintenance mode, with critical fixes only until 2026-11-05. Its
authors' successor is Zensical.

## Decision Outcome

- `docs/` is organized by Diátaxis: tutorials, how-to guides, reference and explanation. ADRs
  live in `docs/adr/`.
- The site is built with Zensical and published to GitHub Pages from the first public
  release.
- Diagrams are Mermaid inside Markdown, which GitHub renders, drawn in C4 style (system
  context and containers).
- Reference pages are generated where possible: configuration schema, CLI help, MCP tool list.

### Consequences

- Good, because there is one source, and diagrams are reviewed like code.
- Bad, because Zensical is young. The docs stay plain Markdown so the generator can be
  replaced cheaply.

### Confirmation

The docs site builds in CI; generated reference pages are checked for drift.
