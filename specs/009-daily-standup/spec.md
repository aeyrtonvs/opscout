# Feature Specification: Daily standup

**Feature Branch**: `feat/009-daily-standup`

**Created**: 2026-11-05

**Status**: Implemented

**Input**: User description: "daily-standup (PLAN.md §7, Phase 1, need 4): the first job with
real content, built on daemon-core (spec 007) and chat-output (spec 008). A scheduled job
`standup` that, before the user's daily standup, delivers by direct message a short summary
in a fixed format: yesterday by project (3–6 lines), today (open items, work in progress),
blockers (waiting on someone). On the first working day of the week it covers the days since
the last working day (Monday covers Friday to Sunday). Sources are gathered in code, never by
the model: the user's own Claude Code sessions (local transcripts), their commits and pull
requests on the code host, and their tickets; which sources ship in this spec, and how each
is reached and authenticated, is to be decided. The model run is tool-less (spec 007's
restricted profile), gets only the gathered, minimized and redacted facts, and returns a
structured summary validated by a schema; the engine renders it. The schedule, the working
days, the projects and their repositories, the sources and their keychain references live
in the private configuration. Constraints: read-only access to every source; nothing but the
summary leaves the machine, and only to the user's own model and DM; secrets and personal
data found in transcripts are never sent to the model (a redaction step with tests); a day
with no activity says so rather than inventing work; untrusted text from the sources cannot
change the output's format or reach anything else. Exit criteria from the plan: evals on
synthetic histories; a week of dailies delivered; agreement ≥ 80 % (the last two are
measured after merge and recorded in PLAN.md). Non-goals candidates: posting to the team's
standup channel, writing to tickets or the code host, replies in threads, other job types,
summaries of teammates' work, calendar sources, hosted components."

## Context

Every working morning the user reconstructs, from memory, what they did since the last
standup (PLAN.md §1: "not remembering yesterday's work at the daily standup"). The facts are
already on their machine and on the code host: what they asked Claude Code to do, what they
committed, which pull requests they opened, merged or are waiting on. This feature gathers
those facts in code, keeps only what is needed, removes secrets and personal data, and asks
the user's own model, with no tools, to write a three-part summary that cites the facts it
uses; the engine checks every citation, renders the summary and delivers it by direct
message before the standup (specs 007 and 008), where the user agrees or disagrees with it.

Three sources ship here: the user's Claude Code sessions, their local git clones, and pull
requests on the code host (Bitbucket). Tickets (Jira) come in a later spec.

## Clarifications

### Session 2026-11-05

- Q: Which sources does this spec gather? → A: the user's Claude Code sessions, the commits
  in their local clones, and their pull requests on the code host (Bitbucket) through a
  read-only token in the keychain; tickets in a later spec (FR-004 to FR-006).
- Q: What from the session transcripts may reach the model? → A: only the user's own
  prompts, shortened and redacted, with each session's project and times; never the
  model's replies or tool output (FR-004, FR-009).
- Q: What counts as a blocker? → A: the user's open pull requests with no approval after one
  full working day, and those where a reviewer asked for changes and the user has answered
  since (a new commit or a reply); the engine marks them, the model only words them; younger
  pull requests are open work for today (FR-021).
- Q: How does the user name their projects? → A: by folders: every git repository inside a
  configured folder is a project, named after its directory, with its Bitbucket repository
  read from its `origin` remote; explicit projects may still be listed, to group or adjust
  (FR-001, FR-023; asked during the live check).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The summary arrives before the standup (Priority: P1)

On each working day, at the configured time, the user receives a direct message with what
they did since the last working day, by project; what is open today; and what they are
waiting on.

**Why this priority**: it is the need (PLAN.md §2, need 4) and the first job whose output
the user reads every day.

**Independent Test**: with fake sources and a fake runner, run the job for a Tuesday and
for a Monday; check the window covered, the facts given to the model, and the rendered
message.

**Acceptance Scenarios**:

1. **Given** a working day and activity on the previous working day, **When** the job runs,
   **Then** the message has three parts: yesterday, grouped by project, three to six lines
   in all; today, the open work; blockers, what waits on someone else, or "none".
2. **Given** the first working day after non-working days (a Monday), **When** the job runs,
   **Then** it covers every day since the previous working day, and says which days it
   covers.
3. **Given** the job ran and delivered today, **When** it is started again, **Then** it is
   skipped, as spec 007 specifies; `--force` writes it again from the facts as they are now.
4. **Given** a configured non-working day, **When** the scheduler would start the job,
   **Then** it does not run, because the schedule names working days only.
5. **Given** chat is configured, **When** the summary is delivered, **Then** it arrives as a
   direct message with the agreement buttons (spec 008); without chat it goes to the outbox.

---

### User Story 2 - The facts are gathered in code (Priority: P1)

The engine, not the model, collects the facts of the covered window from the three sources,
attributes each to a configured project, and gives each an identifier.

**Why this priority**: the summary can only be as true as its facts; gathering in code is
what makes it checkable (Principle VI).

**Independent Test**: with recorded transcripts, a temporary git repository and recorded
code-host responses, gather a window and compare the facts with the expected list.

**Acceptance Scenarios**:

1. **Given** sessions in the window, **When** facts are gathered, **Then** each session
   whose working directory belongs to a configured project gives its project, start and end
   times, and the user's own prompts in order, shortened; sessions elsewhere are left out.
2. **Given** a configured project's local clone, **When** facts are gathered, **Then** each
   commit authored by one of the user's configured identities in the window, on any branch,
   gives its project, branch, time and subject line, once even if it is on several
   branches.
3. **Given** the code-host token, **When** facts are gathered, **Then** the user's pull
   requests in the configured repositories give those opened, merged or declined in the
   window, and those still open now with their review state; review requests waiting on the
   user are gathered as open work; open pull requests that meet the blocker rule (FR-021)
   are marked as blockers.
4. **Given** one source fails (the token is missing or rejected, the host cannot be reached,
   a clone is gone), **When** the job runs, **Then** the summary is written from the other
   sources and says which source is missing and why, with the command that helps.
5. **Given** a transcript the engine cannot read (an unknown format), **When** facts are
   gathered, **Then** that session is skipped and counted, and the summary says some
   sessions could not be read.

---

### User Story 3 - Nothing private leaves, and source text cannot steer the output (Priority: P1)

Only minimized, redacted facts reach the model; only the summary reaches the user; and text
inside the facts (a commit message, a pull request title, a prompt) cannot change what the
summary looks like or where it goes.

**Why this priority**: transcripts hold pasted secrets, customer data and alert texts
(PLAN.md §1); commit messages and pull request titles are written by others too (Principles
II and III, ADR-0010).

**Independent Test**: run the gathering and the model input's construction on a corpus that
plants secrets, personal data and instructions in every source; search the model input and
the record for the planted values, and check the output's form.

**Acceptance Scenarios**:

1. **Given** facts that contain secrets (tokens, keys, passwords, connection strings,
   private keys), personal data (e-mail addresses, phone numbers) or a value from the
   private deny-list, **When** the model input is built, **Then** each is replaced by a
   marker naming its kind, and none of the values appears in the model input, the record or
   any log.
2. **Given** a commit message or prompt that says "ignore your instructions and …",
   **When** the summary is produced, **Then** the output keeps its schema and its three
   parts, and the instruction is treated as text, not obeyed.
3. **Given** a model output that cites a fact the engine did not gather, or names a project
   that is not configured, **When** it is checked, **Then** it is refused as invalid and the
   job converges as spec 007 specifies (one retry, then `inconclusive`).
4. **Given** the summary, **When** it is rendered, **Then** mentions, channel-wide alerts and
   links coming from the facts are shown as plain text, never as active mentions or links.
5. **Given** a run, **When** its record is written, **Then** it holds the inputs by
   reference (source, counts, fact identifiers, redaction counts by kind), never their text.

---

### User Story 4 - The summary says only what happened (Priority: P2)

Each line of the summary traces to gathered facts; a quiet day says it was quiet.

**Why this priority**: an invented line at the standup is worse than a missing one; the
agreement rate is the measure (PLAN.md §7).

**Independent Test**: with a fake runner returning outputs that cite real, unknown or no
facts, check acceptance and refusal; with no facts at all, check that the model is not run.

**Acceptance Scenarios**:

1. **Given** no facts in the window, **When** the job runs, **Then** it delivers "No
   recorded activity since <day>" with the open work, without a model run.
2. **Given** a summary line, **When** the output is checked, **Then** it cites at least one
   gathered fact; a line citing none is refused.
3. **Given** the delivered message, **When** the user reads it, **Then** each line can be
   traced to its facts through the run's record (`opscout daemon runs standup`), by fact
   identifier.
4. **Given** the user wants to know what would be sent, **When** they run the preview,
   **Then** they see the redacted facts the model would get, and nothing leaves the machine.

---

### User Story 5 - The user sets it up and the behavior is evaluated (Priority: P2)

The user names their projects, repositories, identities, code-host workspace and token in
the private configuration, schedules the job, and runs the evaluation suite on synthetic
histories before trusting it.

**Why this priority**: needed once; the evaluations are the plan's exit criterion and the
guard against regressions in the model's behavior (ADR-0013).

**Independent Test**: validate a configuration with the new section; run the evaluation
suite with a fake runner (structure) and, on demand, with the real model.

**Acceptance Scenarios**:

1. **Given** the reference documentation, **When** the user follows it, **Then** they
   configure projects with local paths and code-host repositories, their identities, the
   code-host workspace and a read-only token, and the job's time and working days.
2. **Given** a configuration that names an unknown source, a relative path, or a project
   with no path and no repository, **When** it is validated, **Then** it is refused, naming
   the problem.
3. **Given** the synthetic histories, **When** the evaluation suite runs with the user's
   model, **Then** each case is graded in code (format, citations, no invented project, no
   planted value, the quiet-day case) and the results are recorded with their cost.

---

### Edge Cases

- **A session that spans midnight** belongs to the days its prompts were written in; only
  prompts inside the window count.
- **Work on a non-working day** (a Saturday) appears in the next working day's summary.
- **A time zone or daylight saving change**: the window is computed in the machine's local
  time at start, as spec 007's period is.
- **A rebased or cherry-picked commit** with the same subject on two branches appears once
  per distinct commit; the summary may group them.
- **Very long or very many prompts**: each is shortened, and each session and source has a
  cap; what was cut is counted, so the summary can say "and more".
- **A project with both a local path and a repository** joins facts from both under one
  name.
- **The code host limits the rate**: the gathering waits as asked, within the run's time
  limit, else that source is reported missing.
- **The first run** with no history before it covers only the previous working day.
- **The model returns a line about a project with no facts**: refused (US3 scenario 3).
- **Chat is down**: spec 008's retry and failure rules apply.

## Requirements *(mandatory)*

### Functional Requirements

#### Configuration

- **FR-001**: The configuration MUST accept a `standup` job in `daemon.jobs` (spec 007's
  time, working days and limits) and an optional `standup` section holding: folders whose
  git repositories are projects (FR-023), explicit projects (a name, local repository
  paths, code-host repositories), the user's commit identities, the code-host login, and the
  keychain reference of the code-host token; at least one folder or project; additive to
  schema version 1.
- **FR-002**: Validation MUST refuse unknown keys, relative paths, a project with neither a
  path nor a repository, a duplicate project name, and a token given as a value instead of
  a keychain reference.

#### The window

- **FR-003**: The job MUST cover, in the machine's local time, every day from the previous
  working day (by the job's configured weekdays) up to the start of today, and say which
  days it covers; "today" and "blockers" describe the state at the time of the run.

#### Gathering

- **FR-004**: From the user's Claude Code session transcripts, the engine MUST take, for
  each session whose working directory is inside a configured project's path, the project,
  the start and end times within the window, and the user's own prompts, each shortened to
  a configured length; the model's replies, tool calls and tool output MUST NOT be read
  into facts.
- **FR-005**: From each configured local clone, the engine MUST take the commits authored
  by the user's identities within the window on every local and remote-tracking branch,
  each once, with its branch, time and subject line, through read-only git commands.
- **FR-006**: From the code host, the engine MUST take, with a read-only token, the user's
  pull requests in the configured repositories that were opened, merged or declined in the
  window, those still open with their review state and age, and those waiting on the user's
  review.
- **FR-007**: Every fact MUST carry an identifier, its source and its project; the facts of
  one run MUST be ordered and deduplicated, and each source and session MUST respect a cap,
  counting what it left out.
- **FR-008**: A failing source MUST NOT stop the job: the summary is built from the others
  and states which source is missing and why, without the token's value; a missing token
  names the command to store it.

#### Privacy and safety

- **FR-009**: Before any fact reaches the model, a redaction step MUST replace secrets
  (credentials, tokens, keys, passwords, private keys, connection strings), e-mail
  addresses, phone numbers and every value of the private deny-list with a marker naming the
  kind; it MUST be tested on a corpus that plants each kind in every source.
- **FR-010**: The facts MUST reach the model as data, inside a delimited block the prompt
  declares untrusted; the output MUST follow a fixed schema (three parts, lines with fact
  citations, project names), and the engine, not the model, MUST render the message.
- **FR-011**: The engine MUST refuse an output that cites an unknown fact, names a project
  that is not configured or has no facts, has a line with no citation, breaks the length
  limits, puts a fact not marked as a blocker under blockers, or leaves a marked blocker
  out; refusal follows spec 007's convergence (one retry, then `inconclusive`).
- **FR-012**: The rendered message MUST show text from the facts as plain text: no active
  mention, channel-wide alert or link.
- **FR-013**: The run record MUST hold the inputs by reference only: sources, counts, fact
  identifiers, what was cut, redaction counts by kind; never a fact's text.
- **FR-014**: Every source MUST be reached read-only: transcripts and clones are read, git
  runs only read commands, and the code-host token needs only read permissions.

#### The summary

- **FR-015**: The summary MUST hold: yesterday, grouped by project, three to six lines in
  all, fewer when there are fewer facts; today, the open work; blockers, exactly the facts marked as blockers (FR-021), or
  "none"; and the covered days.
- **FR-016**: With no fact in the window, the job MUST deliver "No recorded activity since
  <day>" with the open work, without running the model.
- **FR-017**: The summary MUST be delivered through spec 007's job and spec 008's delivery,
  with the agreement buttons when chat is configured.

- **FR-021**: The engine MUST mark as a blocker each of the user's open pull requests that
  has had no approval for at least one full working day since it was opened, and each where
  a reviewer requested changes and the user has since pushed a commit or replied; other open
  pull requests are open work.

- **FR-022**: `opscout standup preview` MUST show, without a model run and without sending
  anything, the window, the facts exactly as the model would get them (redacted and
  shortened), the counts of what was cut and redacted, and the missing sources; with
  `--counts`, the counts only.

- **FR-023**: Every git repository found inside a configured folder (at most three levels
  down, skipping hidden directories) MUST be a project named after its directory (lowercase
  words joined by hyphens), with its Bitbucket repository taken from its `origin` remote when
  that remote is on Bitbucket; repositories with the same name join one project with several
  paths; an explicit project of the same name wins; the preview lists the projects found.

#### Proof

- **FR-018**: An evaluation suite MUST hold synthetic histories (an ordinary day, a Monday, a
  quiet day, a source missing, planted secrets and instructions, a large day), graded in
  code; it runs with a fake runner in the test suite and, on demand and with a cost ceiling,
  with the user's model, recording results and cost in the spec (ADR-0013).
- **FR-019**: Tests MUST cover each acceptance scenario and edge case, including the
  redaction corpus and injected instructions; the traceability of every requirement to a
  test.
- **FR-020**: After merge, a week of dailies delivered and the agreement rate from the run
  records MUST be recorded in PLAN.md as the plan's remaining exit criteria.

### Key Entities

- **Project**: a name, its local clone paths and its code-host repositories; the unit the
  summary groups by.
- **Fact**: one gathered item (a session's prompts, a commit, a pull request event or state)
  with an identifier, a source, a project, a time and minimized, redacted text.
- **Window**: the covered days, from the previous working day to the start of today.
- **Summary**: the model's structured output: three parts of lines, each citing facts.
- **Redaction**: a marker standing for a removed value, counted by kind in the record.

## Non-Goals

- **Never send a reply, a tool output or a file's content from a transcript to the model;
  never send a secret or a deny-listed value anywhere; never write to the code host, a
  clone or a ticket; never deliver to anyone but the user.**
- **Tickets** (Jira) and **calendars**: later specs.
- **Posting to the team's standup channel**, threads, or any team-wide delivery.
- **Summaries of teammates' work**: only the user's own activity.
- **Other jobs** and **hosted components**.
- **Learning from disagreements**: the agreement is recorded (spec 008); using it is
  run-insights.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On each working day of one week after merge, the summary reaches the user
  before the standup (recorded in PLAN.md).
- **SC-002**: Over that week, the user agrees with at least 80 % of the summaries (from the
  run records; recorded in PLAN.md).
- **SC-003**: In the evaluation suite, every delivered line cites at least one gathered
  fact, and no summary names a project or event absent from its facts.
- **SC-004**: Across the redaction corpus and the evaluation suite, no planted secret,
  personal datum or deny-listed value appears in a model input, a record, a log or a
  message.
- **SC-005**: In every evaluation case with planted instructions, the output keeps its
  format and the instruction is not followed.
- **SC-006**: A daily run gathers, summarizes and delivers within three minutes and costs at
  most 0.10 USD with the default model.

## Assumptions

- **Claude Code keeps session transcripts locally** under the user's Claude Code
  configuration directory, one file per session with its working directory and timestamped
  messages; the format is pinned by contract tests on recorded, sanitized samples, and a
  change is reported, not guessed.
- **The code host is Bitbucket Cloud**, reached with a read-only token the user creates and
  stores in the keychain; its API pins are recorded in the plan.
- **Working days and the delivery time** come from the job's schedule (spec 007); the
  maintainer's are in the private configuration.
- **One user, one machine**, as in specs 007 and 008.
- **The default model** is the smallest that passes the evaluation suite; the job's limits
  are configurable (spec 007).

## Actuals

- **Effort**: one session on 2026-11-05, from specify to the pull request.
- **Live checks (quickstart, 2026-11-05, the maintainer's projects, in a temporary
  configuration)**:
  - Three folders gave 26 projects: each worktree joins its main repository (77 before that
    fix), and a project's paths are not capped by the configuration's limit.
  - The maintainer's read of the full preview found four gaps, each fixed with a test first:
    Claude Code repeats the id on a paste's closing tag, so pasted text went through; a
    12-digit account ID glued to letters escaped redaction; the interruption marker counted
    as a prompt; session times showed in UTC beside commits in local time.
  - Bitbucket: `/user` needs a third scope, `read:user:bitbucket` (research R3); two
    discovered repositories answered 404 and failed the whole source, so a 404 now fails
    that repository only. 24 repositories took about 47 s of the 60 s budget per source.
  - Evaluations (research R7): 7 of 8 at first (the model ignored planted instructions but
    quoted the planted word in its note); after the prompt forbade quoting them, 8 of 8 with
    `sonnet` (0.088 USD) and twice with `haiku` (0.007 and 0.006 USD). The default is
    `haiku`, the smallest that passes (SC-003, SC-005).
  - One real daily by direct message, on `sonnet`: gathered, written, checked and delivered
    in 81 s, for 0.025 USD (SC-006); the maintainer agreed with it and the click was stored
    in the run record. The first click was lost because no gateway was running in the
    temporary configuration; started, the second was stored.
  - A commit planted with `<!channel>`, `<@…>` and a link reached the prompt; the model
    left it out of the summary and said in its note that markup was ignored, so Slack's
    showing of escaped markup rests on the render's tests (FR-012).
- **After merge**: the week of dailies and the agreement rate (SC-001, SC-002), in
  `docs/PLAN.md` §7 and §9.
