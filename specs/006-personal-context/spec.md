# Feature Specification: Personal context

**Feature Branch**: `feat/006-personal-context`

**Created**: 2026-11-04

**Status**: Implemented

**Input**: User description: "personal-context (Phase 0b, docs/PLAN.md §7; need 6). Renders
a marked section of `~/.claude/CLAUDE.md` from config; shows a diff and writes only on
confirmation. Exit criteria: idempotent; content outside the markers untouched."

## Context

The same facts are retyped across sessions: the language to answer in, the time zone that
times are given in, which account and profile to use, the rules for touching production
(PLAN.md §1). Claude Code reads the user's own instructions file, `CLAUDE.md` in its
configuration directory (`CLAUDE_CONFIG_DIR`, or `~/.claude`), at the start of every
session in every project. Those facts belong in the private configuration (Principle V),
and this feature puts them in that file.

The engine renders the configured facts into one marked block of that file. It always shows
the change as a diff first, and it writes only after the user confirms. Everything outside
the block stays byte for byte as the user wrote it. Writing a file in the user's home is a
change outside the repository, so the confirmation is a mechanism, not a prompt
(Principles II and IV).

## Clarifications

### Session 2026-11-04

- Q: What shape does the configuration give the personal context? → A: Typed `language` and
  `timezone` (an IANA time zone), plus `sections`: headings, each with a list of lines.
- Q: How is "shows a diff and writes only on confirmation" guaranteed? → A: `opscout context
  apply` shows the diff and, in a terminal, asks yes or no. Without a terminal (as when
  Claude runs it) it writes only with `--confirm <code>`, the code `opscout context diff`
  printed with the same diff, and only while the file and the configuration still give that
  diff. No skill.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every session knows the user's context (Priority: P1)

The user writes the facts once in the private configuration and applies them. From then on,
every Claude Code session starts with them.

**Why this priority**: it is the value of the feature: the facts stop being retyped.

**Independent Test**: with a configuration and a temporary configuration directory, run
the diff, apply with its code, and read the file.

**Acceptance Scenarios**:

1. **Given** a configuration with a `personal_context` section and no `CLAUDE.md`, **When**
   the user applies it, **Then** the file is created holding only the marked block.
2. **Given** a `CLAUDE.md` without the block, **When** the user applies, **Then** the block is
   added at the end, after a blank line, and every byte before it is unchanged.
3. **Given** a `CLAUDE.md` with the block, **When** the configuration changes and the user
   applies, **Then** only the block's content changes.
4. **Given** the block is already up to date, **When** the user applies again, **Then**
   nothing is written and the user is told so.
5. **Given** the block, **When** it is rendered, **Then** it holds the language to answer in,
   the time zone, and each configured section's heading and lines, in the configured order,
   and says that it is generated from the configuration.

---

### User Story 2 - Nothing is written without the user's say (Priority: P1)

The user always sees exactly what will change before it changes, and the change is the one
they saw.

**Why this priority**: the file shapes every session; a silent or unexpected write there is
worse than no feature.

**Independent Test**: run apply without confirmation, with a wrong code, and after changing
the file or the configuration between diff and apply; check that the file is unchanged.

**Acceptance Scenarios**:

1. **Given** a pending change, **When** the user runs the diff, **Then** they see a unified
   diff of the file and a confirmation code, and nothing is written.
2. **Given** a terminal, **When** the user runs apply, **Then** the diff is shown, the user is
   asked to confirm, and the file is written only on yes.
3. **Given** no terminal, **When** apply runs without a code, **Then** nothing is written and
   it prints the diff and the code to confirm with.
4. **Given** a code, **When** the file or the configuration has changed since the diff,
   **Then** nothing is written and the user is asked to look at the diff again.
5. **Given** the right code, **When** apply runs without a terminal, **Then** the file is
   written.

---

### User Story 3 - The user's own file is safe (Priority: P2)

Whatever the file holds, apply either writes the change correctly or writes nothing.

**Why this priority**: the file is the user's; a damaged instructions file breaks every
session.

**Independent Test**: run apply on files with broken markers, other encodings, symlinks and
CRLF line endings.

**Acceptance Scenarios**:

1. **Given** a file with only one marker, markers out of order, or the block twice, **When**
   the user runs the diff or apply, **Then** nothing is written and the message says which
   marker is wrong and on which line.
2. **Given** a file that is not UTF-8, or is larger than 1 MiB, **When** the user runs apply,
   **Then** nothing is written and the reason is given.
3. **Given** `CLAUDE.md` is a symbolic link, **When** the user applies, **Then** the file it
   points to is changed and the link stays a link.
4. **Given** a file with CRLF line endings, **When** the user applies, **Then** the block uses
   CRLF too.
5. **Given** a write that fails half-way, **When** the user looks at the file, **Then** it
   holds either the old content or the new, never a mix.

---

### Edge Cases

- **No `personal_context` section.** The diff and apply say there is nothing to render and
  write nothing, even when the file holds an old block (removing it is the user's edit).
- **An invalid configuration.** Nothing is rendered; the message points to
  `opscout config validate`.
- **`CLAUDE_CONFIG_DIR`** names another directory: its `CLAUDE.md` is the target. `--target
  <file>` names any other file.
- **The configuration directory does not exist.** Apply creates it, then the file.
- **A configured line holding the marker text.** Refused by validation, so the block can
  always be found again.
- **A different newline at the end of the file.** A file without a final newline gets one
  before the blank line and the block. A file that ends in a bare carriage return is not
  written: the added newline would change its line endings.
- **Lines** are broken at newlines only, as editors break them; a form feed or a Unicode line
  separator inside a line is kept as it is. A byte order mark before a first-line marker is
  kept.
- **A target that is not a regular file** (a directory, a named pipe) is not read or
  written.
- **The file changes while the user is being asked**, as when Claude Code saves a memory
  there: nothing is written, and the user is asked to run apply again.

## Requirements *(mandatory)*

### Functional Requirements

#### Configuration

- **FR-001**: The configuration MUST accept an optional `personal_context` section, added to
  schema version 1 as an additive change (spec 002), with `language` (one line),
  `timezone` (an IANA time zone name) and `sections` (headings, each with a list of lines),
  at least one of them present.
- **FR-002**: Validation MUST refuse a heading or line that spans lines, is empty, is too
  long, or holds the marker text, and an unknown time zone.

#### Rendering

- **FR-003**: An engine command MUST print the rendered block, which starts and ends with
  one marker line each and holds, in order: a note that it is generated from the
  configuration, the language, the time zone, and each section as a heading with its lines.
- **FR-004**: Rendering MUST depend only on the configuration, so the same configuration
  always gives the same block.

#### Diff and apply

- **FR-005**: The target MUST be `CLAUDE.md` in `CLAUDE_CONFIG_DIR`, or in `~/.claude`, unless
  `--target` names another file.
- **FR-006**: The new content MUST replace the block between the markers, or append the
  block after a blank line when there is none, leaving every other byte unchanged.
- **FR-007**: `opscout context diff` MUST print a unified diff of the target and a
  confirmation code derived from the current content and the new content, and never write.
  Exit 0 when there is nothing to change, 1 when there is.
- **FR-008**: `opscout context apply` MUST write only when the user confirms in a terminal,
  or when `--confirm` gives the code of the current diff; otherwise it MUST write nothing and
  print the diff and the code. With nothing to change it MUST write nothing.
- **FR-009**: A file with malformed markers, not UTF-8, or above 1 MiB MUST NOT be written;
  the message MUST give the reason, with the line for a marker.
- **FR-010**: A write MUST replace the file in one step, through a symbolic link to its
  target, keeping the file's permissions, and creating the directory when needed.

#### Proof

- **FR-011**: Tests MUST cover each acceptance scenario and edge case, including applying
  twice (idempotent) and content outside the markers kept byte for byte.

### Key Entities

- **Personal context**: the `personal_context` section: language, time zone, sections.
- **Block**: the marked part of the target that the engine owns.
- **Pending change**: the target's current content, its new content, the diff, and the
  confirmation code.

## Non-Goals

- **Never write without a confirmation, never change anything outside the markers, and
  never write any file but the target.**
- **Removing the block.** The user deletes it by hand.
- **A skill or a hook.** The user, or Claude with the user's permission, runs the commands.
- **Other instruction files by default** (`AGENTS.md`, a project's `CLAUDE.md`); `--target`
  covers a one-off.
- **Merging with what the user wrote by hand inside the block.** The block is the engine's;
  the diff shows a hand edit being replaced.
- **Checking the lines for secrets.** The configuration holds none by contract (spec 002);
  the lines are the user's own text.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Applying the same configuration twice writes once; the second run changes no
  byte and no modification time.
- **SC-002**: In 100 % of the tests, every byte outside the markers is unchanged after apply.
- **SC-003**: 0 writes without a terminal yes or a matching code across the test set.
- **SC-004**: 100 % of the functional requirements are covered by a test.

## Assumptions

- **Claude Code reads `CLAUDE.md` in its configuration directory** (`CLAUDE_CONFIG_DIR` or
  `~/.claude`) in every session; checked in the CLI 2.1.318.
- **The markers are HTML comments**, invisible when the Markdown is rendered and kept by
  Claude Code as text.
- **The confirmation code is short** (12 hexadecimal characters of a SHA-256): it guards
  against a change between diff and apply, not against an attacker.
- **No eval suite**: there is no skill, so the proof is tests (ADR-0013 covers skills).
