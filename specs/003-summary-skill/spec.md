# Feature Specification: Summary skill

**Feature Branch**: `feat/003-summary-skill`

**Created**: 2026-11-04

**Status**: Draft

**Input**: User description: "summary-skill (Phase 0b, docs/PLAN.md §7; need 5). Write-up
formats from config: ticket, message, postmortem; a contract whose non-goals include
'never list what was ruled out'. The skill gets its formats from the engine, which reads
the validated configuration: the plugin runs the engine through a launcher in its `bin/`
(decided 2026-11-04, ADR to follow). Exit criteria: eval suite at threshold and above the
no-plugin baseline."

## Context

The maintainer asks Claude, again and again, for "a short summary, ready to paste into a
ticket or a message", and then corrects it: shorter, plainer, and "don't list what was
ruled out" (PLAN.md §1). The wanted shape is the same every time, so it belongs in the
configuration (Constitution Principle V) and in a skill that applies it (need 5).

This is the first feature that reads the configuration from inside Claude Code. Spec 002
says only the engine's loader reads `config.yaml` (its FR-032), and the plugin cannot run
the engine yet (PLAN.md §9). On 2026-11-04 the maintainer decided that this feature settles
that: the plugin runs the engine through a launcher, and the skill takes its formats from
an engine command. The decision gets its own ADR.

## Clarifications

### Session 2026-11-04

- Q: How should the skill get the write-up formats from the private configuration, given
  that only the engine's loader may read it? → A: The plugin runs the engine, through a
  launcher in the plugin's `bin/` that runs the package with uv at the plugin's version;
  the skill injects the output of an engine command that prints the formats (validated
  configuration plus built-in defaults). An ADR records it, and the MCP server reuses it.
- Q: What threshold and cost ceiling apply when the evals run on the maintainer's login? →
  A: Threshold 0.9 and a ceiling of USD 3 per run, each run confirmed by the maintainer
  (FR-028).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A write-up of the work, ready to paste (Priority: P1)

After working through a problem in a Claude Code session, the user asks for a summary for
a ticket, a chat message or a postmortem. They get one block of plain text in the right
shape: only the useful facts from the session (what happened, why, what was done, what is
pending), short, ready to paste. What was considered and ruled out, and how the result was
reached, are left out.

**Why this priority**: it is need 5 itself, and it removes the most frequent correction.

**Independent Test**: give the skill a synthetic session in which several hypotheses were
ruled out before the cause was found, ask for each kind of write-up, and check the shape,
the length and that no ruled-out hypothesis appears.

**Acceptance Scenarios**:

1. **Given** a session that found and fixed a problem after ruling out other causes,
   **When** the user asks for a ticket summary, **Then** the reply holds one block in the
   ticket format (what happened, why, what was done, what is pending) and names none of the
   ruled-out causes.
2. **Given** the same session, **When** the user asks for a message, **Then** the reply is
   a short message in the message format, within its length limit.
3. **Given** a session about an incident, **When** the user asks for a postmortem, **Then**
   the reply follows the postmortem format (cause, impact, fix, follow-ups).
4. **Given** a session in which nothing is pending, **When** a format has a "pending"
   section, **Then** the section says so in a few words rather than inventing work.
5. **Given** any write-up, **When** it is produced, **Then** it contains only facts stated
   in the session: no invented ticket numbers, names, times or figures, and no secret
   values.
6. **Given** a request that names no kind, **When** the skill runs, **Then** it uses the
   ticket format, says which format it used, and lists the others.

---

### User Story 2 - The formats are the user's own (Priority: P1)

The user describes their formats once, in their private configuration: the sections in
order, the rules, a length limit, and optionally the language. The skill applies them.
Without configuration, sensible built-in formats apply.

**Why this priority**: the formats differ between people and teams (Principle V); without
this the skill is a fixed prompt.

**Independent Test**: validate configurations with a `writeups` section, print the
formats the engine resolves from each, and check the skill's output against a configured
format that differs from the built-in one.

**Acceptance Scenarios**:

1. **Given** no `writeups` section, **When** the formats are printed, **Then** the built-in
   ticket, message and postmortem formats are shown, marked as built-in.
2. **Given** a configured format with the name of a built-in one, **When** the formats are
   printed, **Then** the configured format replaces the built-in one entirely.
3. **Given** a configured format with a new name, **When** the user asks for it by name,
   **Then** the skill writes in that format.
4. **Given** rules set for every format, **When** any write-up is produced, **Then** those
   rules apply on top of the format's own.
5. **Given** a configured language, **When** a write-up is produced, **Then** it is written
   in that language; without one, it is written in the language the user writes in.
6. **Given** an invalid `writeups` section, **When** the configuration is validated, **Then**
   each problem is reported as spec 002 requires.

---

### User Story 3 - The plugin runs the engine it belongs to (Priority: P1)

The skill calls the engine through the plugin. The launcher runs the engine version that
matches the plugin: from the clone when the plugin is loaded from source, or the released
version otherwise. When it cannot, the skill says why and what to do instead of failing
silently.

**Why this priority**: without it, the skill cannot read the configuration at all; it is
the mechanism every later plugin feature (the MCP server, hooks) reuses.

**Independent Test**: run the launcher from a clone and from a copy of the plugin directory
outside the clone, with and without a released version, and check which engine runs or
what message is printed.

**Acceptance Scenarios**:

1. **Given** the plugin loaded from a clone of this repository, **When** the launcher runs,
   **Then** it runs the engine from that clone.
2. **Given** the plugin installed from the marketplace at a released version, **When** the
   launcher runs, **Then** it runs the engine of exactly that version.
3. **Given** an installed plugin whose version has no release, **When** the launcher runs,
   **Then** it prints why and how to load the plugin from a clone, and exits with failure.
4. **Given** uv is missing, **When** the launcher runs, **Then** the failure names the
   missing `uv` command, and the plugin's README says uv is required and where to get it.
5. **Given** the configuration directory is missing or invalid, **When** the skill loads,
   **Then** the user is told what is wrong and how to check it; a missing directory falls
   back to the built-in formats with a note, and an invalid configuration stops the
   write-up.

---

### Edge Cases

- **A session with nothing worth summarizing.** The skill says so and asks what to cover,
  instead of producing filler.
- **A kind the configuration does not define.** The skill lists the defined kinds and asks.
- **Ruled-out hypotheses that are also part of the cause** (a first guess that turned out
  right). They are facts of the result, not ruled-out items, and may appear.
- **Secrets seen in the session.** A write-up never contains a secret value, even when the
  session showed one; it may say that a secret exists and where.
- **A request to post the write-up somewhere.** The skill only writes the text; posting is
  out of scope.
- **Very long sessions.** The write-up still respects the format's length limit.
- **A format with no sections.** Allowed: the write-up is free text under the format's
  rules and limit.
- **A configured language the user does not write in.** The configured language wins.

## Requirements *(mandatory)*

### Functional Requirements

#### Formats in the configuration

- **FR-001**: The configuration MUST accept an optional `writeups` section, added to schema
  version 1 as an additive change (spec 002, FR-029 and FR-030).
- **FR-002**: `writeups` MUST hold an optional `language`, optional `rules` that apply to
  every format, and optional `formats`: a mapping from a format name to its definition.
- **FR-003**: A format MUST hold a one-line `description`, optional `sections` (headings
  in order), optional `rules`, and an optional `max_lines` (a positive integer).
- **FR-004**: Format names MUST be lowercase words joined by hyphens, so that they can be
  typed as an argument.
- **FR-005**: The engine MUST ship built-in `ticket`, `message` and `postmortem` formats.
  Their rules MUST include never listing what was evaluated and ruled out, nor how the
  result was reached.
- **FR-006**: A configured format MUST replace the built-in format of the same name
  entirely; a configured format with a new name MUST be added to the built-in ones.
- **FR-007**: The built-in formats MUST contain no organization-specific term (Constitution
  Principle I).

#### Printing the formats

- **FR-008**: An engine command MUST print the resolved formats as plain instructions: for
  each format, its name, description, sections, rules (the shared rules first) and limit,
  and whether it is built-in or configured, plus the language when one is set.
- **FR-009**: The command MUST resolve the configuration directory as spec 002 does (FR-001
  there) and read the configuration only through the engine's loader (FR-032 there).
- **FR-010**: The command MUST always exit with status 0, so that the skill always loads,
  and say in its output what happened: the configuration it read; or that the directory is
  missing, followed by the built-in formats; or that the configuration is invalid, with the
  number of problems and the command that lists them, and no formats.
- **FR-011**: The output MUST be deterministic: the same configuration gives the same text.

#### The skill

- **FR-012**: The plugin MUST provide a `summary` skill that follows the Agent Skills
  specification (ADR-0009): its `name` equals its directory and its description stays
  within the specification's limits.
- **FR-013**: The skill MUST open with its contract (ADR-0018): deliverable, constraints,
  non-goals and acceptance.
- **FR-014**: The skill MUST get the formats by injecting the engine command's output, for
  the configuration directory the plugin was given at install time.
- **FR-015**: The skill MUST produce exactly one block of text in the requested format,
  ready to paste, followed by at most one line naming the format used.
- **FR-016**: The write-up MUST state only facts from the session, MUST NOT list what was
  evaluated and ruled out or how the result was reached, and MUST NOT contain a secret
  value.
- **FR-017**: Without a named kind the skill MUST use `ticket` and list the other kinds; for
  an unknown kind it MUST list the defined kinds and write nothing.
- **FR-018**: When the formats command reports an invalid configuration, the skill MUST
  write nothing and tell the user to run `opscout config validate`.
- **FR-019**: The skill MUST NOT post, send or save the write-up anywhere, and MUST NOT use
  tools other than the injected engine command.
- **FR-020**: The skill MUST run without asking for permission: the plugin pre-approves only
  the formats command.

#### The launcher (ADR to follow)

- **FR-021**: The plugin MUST provide an `opscout` launcher in its `bin/`, written as a
  Python script run through uv (ADR-0021).
- **FR-022**: Loaded from a clone of this repository, the launcher MUST run the engine from
  that clone.
- **FR-023**: Otherwise the launcher MUST run the engine release whose version equals the
  plugin's version, and nothing else, from the package index the releases are published to
  (ADR-0016).
- **FR-024**: When no such release exists, the launcher MUST print why and what to do, and
  exit with a non-zero status. uv runs the launcher itself, so a missing uv is reported by the
  system as a missing `uv` command; the plugin's README MUST state that uv is required.
- **FR-025**: The launcher MUST pass its arguments, standard input, output and exit status
  through unchanged.

#### Proof

- **FR-026**: The skill MUST have an eval suite in the plugin with at least one case per
  acceptance scenario of User Story 1 and User Story 2 that concerns the skill, each named
  after its scenario (`003-us1-s1`), with synthetic sessions only (ADR-0013).
- **FR-027**: The suite MUST use deterministic graders wherever a property can be asserted
  (absence of ruled-out items, sections present, length, single block), and an LLM grader
  only for "only facts from the session".
- **FR-028**: The suite MUST score at least 0.9 and above the no-plugin baseline, run with a
  cost ceiling of USD 3, and the result MUST be recorded in this spec. Until the first
  release, the suite runs through the headless runner of ADR-0013's amendment, because the
  official harness cannot run the engine from a clone.
- **FR-029**: Every functional requirement MUST be covered by a test or an eval case tied to
  it, and the suite MUST fail when one has none.

### Key Entities

- **Write-up format**: a named shape for a write-up: description, sections in order,
  rules, length limit; built-in or configured.
- **Write-ups section**: the configuration's `writeups`: language, shared rules, formats.
- **Resolved formats**: the built-in formats with the configured ones applied, as the
  engine prints them.
- **Launcher**: the plugin's `bin/opscout`, which runs the engine matching the plugin.
- **Eval case**: one synthetic session and request, with graders, traced to a scenario.

## Non-Goals

- **Never list what was evaluated and ruled out**, nor how the result was reached; never
  invent facts; never include a secret value. These are behaviors the skill must never
  show (constitution, Contracts).
- **Posting or saving.** The skill does not create tickets, send messages, or write files;
  the user pastes the text (Principle II, IV).
- **Reading other sources.** The skill summarizes the current session only; it does not
  read tickets, chat, commits or logs (later skills do).
- **Templates with placeholders, rich formatting or per-recipient variants.** Formats are
  sections, rules and a limit.
- **Publishing a release.** The launcher can run released versions; cutting the first
  release is a separate, confirmed step (Principle IV).
- **The MCP server.** It will reuse the launcher, in its own spec.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The eval suite scores at least 0.9, and above the no-plugin baseline, with every acceptance scenario of User Stories 1 and 2 covered.
- **SC-002**: 0 ruled-out hypotheses appear in any eval output.
- **SC-003**: 100 % of eval outputs respect their format's length limit and section order.
- **SC-004**: Printing the formats takes under two seconds from a clone, start-up included.
- **SC-005**: The maintainer's private configuration, with its own write-up formats,
  validates and drives the skill locally; nothing from it reaches this repository.
- **SC-006**: 100 % of the functional requirements are covered by a test or an eval case.

## Assumptions

- **Built-in formats** follow the shape PLAN.md §1 and §2 already state publicly: a ticket
  and a message cover what happened, why, what was done and what is pending; a postmortem
  covers cause, impact, fix and follow-ups.
- **Language**: without `writeups.language`, the write-up follows the language the user
  writes in.
- **The skill may be invoked by the model** when the user asks for a summary in their own
  words, as well as by name; it only writes text, so automatic invocation is harmless.
- **Releases**: none exists yet, so an installed plugin cannot run the engine until the first
  release; loading the plugin from a clone (`claude --plugin-dir plugins/opscout`) is the
  supported way until then.
- **Evals** run locally on the maintainer's own Claude Code login, with a cost ceiling, as
  ADR-0013 states; running them is confirmed by the maintainer.
- **uv** is already a prerequisite (ADR-0020).
