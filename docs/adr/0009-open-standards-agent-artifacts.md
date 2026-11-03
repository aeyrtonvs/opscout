---
status: accepted
date: 2026-11-03
decision-makers: repository maintainer
---

# AGENTS.md, Agent Skills and MCP as the formats for agent-facing artifacts

## Context and Problem Statement

Contributors may use coding agents other than Claude Code, and the skills and tools this
project builds should not depend on one client more than necessary.

Facts (2026-11-03):

- AGENTS.md and MCP are founding projects of the Linux Foundation's Agentic AI Foundation
  (December 2025).
- Claude Code reads AGENTS.md only when there is no CLAUDE.md or CLAUDE.local.md. The
  documented way to share one file across agents is an `@AGENTS.md` import inside CLAUDE.md.
- The Agent Skills specification (agentskills.io) defines `name`, `description`, `license`,
  `compatibility`, `metadata` and an experimental `allowed-tools`. Claude Code adds fields such
  as `effort`, `model`, `context`, `agent` and `hooks`, and ignores fields it does not know.
  claude.ai and the Skills API reject non-standard fields.

## Decision Outcome

1. `AGENTS.md` is the canonical, agent-agnostic guide to working on this repository.
   `CLAUDE.md` imports it and adds only what is specific to Claude Code.
2. Every skill is a valid Agent Skill: `name` equals its directory, and the description stays
   within the specification's limits. Claude Code extension fields are used where they meet a
   measured need: `effort` and `model` per skill (need #6) and `context: fork` for
   investigations. Uploading the skills to claude.ai is not a goal.
3. Tools that agents call are exposed through MCP (ADR-0011).

### Consequences

- Good, because instructions, skills and tools follow formats that other clients adopt.
- Bad, because there are two instruction files (AGENTS.md and a thin CLAUDE.md).
- Bad, because effort and model selection only works in Claude Code; other clients ignore
  those fields.

### Confirmation

CI validates skill frontmatter against the Agent Skills fields plus an allow-list of Claude
Code extension fields.
