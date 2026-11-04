# Feature Specification: Leak guard

**Feature Branch**: `feat/001-leak-guard`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "leak-guard: a specification for the leak check that Phase 0a
built (`tools/leak_check.py`, ADR-0015), which enforces Constitution Principle I and
AGENTS.md hard rules 1–2. It covers three layers: generic patterns kept in this public
repository, a private deny-list read from the private configuration directory, and commit
e-mail addresses. File names are checked as well as contents. It runs on files, tracked
files, a commit message, the commit identity, a range of commits (CI) and the commits being
pushed. Layer-1 false positives go in an allow-list, each with a reason. Output in CI is
always redacted. Deliverable: the spec, a synthetic-leak test suite traced to its
requirements, and pattern changes driven only by real misses and false positives. Exit
criteria: every synthetic leak in the test set is caught; under 1 second on a typical diff."

## Context

This repository is public, and a leak in it cannot be undone (Constitution Principle I).
Phase 0a built the leak check ahead of its specification; the maintainer agreed on
2026-11-03 to bring layers 2 and 3 forward. This spec states what the check must do, so that
its tests trace to requirements and any later change to its patterns is a change in
specified behavior (ADR-0008).

The check is the gate behind AGENTS.md hard rules 1 and 2 (dual encoding, ADR-0018).

## Clarifications

### Session 2026-11-03

- Q: Should the pre-push check also examine the names of the branches and tags being
  pushed, which GitHub publishes with the push? → A: Yes, with layers 1 and 2; a finding
  fails the push.
- Q: Should this feature add IPv6 detection now, or leave it as a non-goal until a real miss
  justifies it? → A: A non-goal until a real miss (FR-027).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Real-looking data is stopped before it is committed (Priority: P1)

A contributor stages a change that contains something shaped like real organizational
data: an account ID, an internal IP address, a chat-platform ID, a ticket key, an internal
hostname, a cloud endpoint that names a resource, or a personal e-mail address. It may be in
a file's contents, in a file's name, or in the commit message. The commit is refused, and
the contributor is told where each finding is, which rule it broke, and how to fix it.

**Why this priority**: this is the gate for hard rule 1. Without it the repository depends
on a manual check, which eventually fails.

**Independent Test**: stage synthetic leaks of each shape, in contents, in file names and in
a commit message, and check that each one is reported and the commit fails; stage reserved
values (`123456789012`, RFC 5737 addresses, `example.com` names) and check that they pass.

**Acceptance Scenarios**:

1. **Given** a staged file whose contents hold a value of a flagged shape, **When** the
   contributor commits, **Then** the commit fails and the output names the file, the line,
   the rule and the value.
2. **Given** a staged file whose *name* holds a value of a flagged shape, **When** the
   contributor commits, **Then** the commit fails and the finding is marked as a file name.
3. **Given** a commit message that holds a value of a flagged shape, **When** the
   contributor commits, **Then** the commit fails and the finding names the message line.
4. **Given** a staged change that holds only reserved or harmless values, **When** the
   contributor commits, **Then** the check passes and prints nothing.
5. **Given** a finding, **When** it is reported, **Then** a hint says how to fix it: replace
   it with a reserved value, or, if it is not real data, allow-list it with a reason.

---

### User Story 2 - The maintainer's private terms are caught without being published (Priority: P1)

The maintainer keeps a private deny-list (organization and product names, profile names,
real account IDs, hostnames, channel names) in the private configuration directory. The
check reads it locally and refuses any commit that contains one of its terms. The terms
never appear in this repository, and an allow-list entry cannot excuse them.

**Why this priority**: generic shapes cannot know a company's name. Only a private list can,
and it must stay private, or the list itself becomes the leak.

**Independent Test**: point the configuration directory at a temporary deny-list with
synthetic terms, then check a file, a file name and a message that hold one of them.

**Acceptance Scenarios**:

1. **Given** a deny-list with a term, **When** a staged file contains that term in any
   letter case, **Then** the commit fails with a `private-term` finding.
2. **Given** a deny-list term that is also in the allow-list, **When** the term is staged,
   **Then** the commit still fails, and the hint says to refine the deny-list instead.
3. **Given** no deny-list in the configuration directory, **When** the check runs, **Then**
   it warns that layer 2 was skipped and continues with the other layers.
4. **Given** a clone that requires the deny-list and has none, **When** the check runs,
   **Then** it fails and says where the deny-list was expected.
5. **Given** a deny-list entry that is not a valid pattern, **When** the check runs,
   **Then** it stops with an error that names the entry's line.

---

### User Story 3 - Commit metadata never reveals an employer (Priority: P2)

A contributor's git identity may be a work address, which names the employer. The check
refuses a commit whose author or committer address is not a GitHub no-reply address, and
tells the contributor which setting to change.

**Why this priority**: commit metadata is published with the commit, and it is the easiest
leak to miss because it is not in the diff.

**Independent Test**: set a synthetic personal address as the identity and commit; set a
no-reply address and commit.

**Acceptance Scenarios**:

1. **Given** an author or committer address outside GitHub's no-reply forms, **When** the
   contributor commits, **Then** the commit fails and the hint names the git setting to
   change.
2. **Given** a no-reply address (with or without the numeric prefix, or a bot's), **When**
   the contributor commits, **Then** the identity passes.
3. **Given** an identity finding, **When** the hint is shown, **Then** it never suggests the
   allow-list.

---

### User Story 4 - Every commit is checked before it leaves the machine and when it reaches CI (Priority: P2)

Commits can skip local hooks (`--no-verify`, a clone without the hooks, a commit made by a
tool). Before a push, every commit the remote lacks is checked with every layer, and so are
the names of the branches and tags being pushed, which GitHub publishes with them. In CI,
every commit of the pull request is checked with layers 1 and 3, and nothing the check
prints there reveals a value, because CI logs are public.

**Why this priority**: the pre-commit gate is only as strong as its weakest bypass. The
push and CI gates close the bypasses.

**Independent Test**: create commits in a scratch repository, one with a synthetic leak
added with the hooks skipped, then run the push check and the range check over them.

**Acceptance Scenarios**:

1. **Given** a range of commits, one of which adds a leak in its contents, its file names,
   its message or its identity, **When** the range is checked, **Then** the check fails and
   names that commit.
2. **Given** a push of several branches, **When** the push check runs, **Then** every local
   commit that the remote does not have is checked, not only the first branch's.
3. **Given** a new branch whose base is unknown to the remote, **When** the push check
   runs, **Then** every commit reachable from the head that the remote lacks is checked.
4. **Given** a run in CI, **When** the check reports a finding, **Then** the output shows the
   rule and location but not the value.
5. **Given** a commit that only deletes a file holding a leak, **When** the range is checked,
   **Then** the deletion does not fail the check.
6. **Given** a push of a branch or tag whose name holds a flagged shape or a deny-list term,
   **When** the push check runs, **Then** the push fails and the finding names the ref.

---

### User Story 5 - False positives are handled openly, and patterns change only on evidence (Priority: P3)

Some harmless values have a flagged shape: a version number that looks like an address, a
line range that looks like a ticket key. A contributor adds the value to the allow-list with
the reason it is not real data. When the check misses a real leak or flags a harmless value
again and again, the pattern changes, starting from a synthetic test case that reproduces
the miss or the false positive.

**Why this priority**: the check must stay usable, or contributors will bypass it. But a
loose pattern is a weakened sensor, so every change must be justified.

**Independent Test**: add an allow-list entry with and without a reason; review that every
pattern change in the history comes with a test case.

**Acceptance Scenarios**:

1. **Given** an allow-list entry with a value and a reason, **When** that value is staged,
   **Then** the check passes.
2. **Given** an allow-list entry without a reason, **When** the check runs, **Then** it stops
   with an error that names the entry.
3. **Given** a pattern change, **When** it is reviewed, **Then** it comes with a synthetic
   test case that failed before the change and passes after it.

---

### Edge Cases

- **Binary files**: a file with a NUL byte has its name checked but not its contents. A file
  that git treats as binary only because of an attribute, but which holds text, is read and
  checked.
- **Symbolic links**: a link is checked by its own name, not its target's.
- **Unusual file names**: names with spaces, quotes or non-ASCII characters are read exactly,
  not in git's quoted form.
- **Paths above the repository**: only the part of a path inside the working directory is
  checked as a name, since the directories above it are the user's own.
- **Verbose commit messages**: the diff that git appends below the scissors line is not part
  of the message and is not checked; comment lines above it are checked, because a cleanup
  setting may keep them.
- **Merge commits**: a merge is checked against its first parent, so only what it brings in
  is checked.
- **Version-like values**: version numbers, standard names (licence identifiers, hash names,
  ADR and requirement IDs) and reserved example values are not reported.
- **Pathological input**: a very long line of dotted labels is scanned in linear time and
  cannot stall the check.
- **No git identity**: when no identity is configured there is no commit to check, so the
  identity check passes.
- **Redacted locations**: a value found in a file or ref name is part of the finding's
  location too, so redaction hides it there as well; found during implementation, where a
  file name in CI output still showed the whole value.
- **Deletions**: removing a leak is never blocked; only added or changed content is checked.
  Likewise, pushing the deletion of a remote branch or tag is not checked.
- **A push with no new commit**: the hook framework runs no pre-push hook when a push brings
  no commit the remote lacks (for example a new branch on a commit already pushed), so its
  ref names are not checked; the confirmation asked before every push (AGENTS.md rule 5) is
  the control left, and PLAN.md §9 records the limit.
- **Ref names**: a branch or tag name is checked as a whole, so a ticket key embedded in
  `fix/<key>-summary` is found; the remote's name and URL are not checked.

## Requirements *(mandatory)*

### Functional Requirements

**Layer 1 — generic patterns (public)**

- **FR-001**: The check MUST report 12-digit account IDs, in plain and in dashed console
  form, except the reserved examples `123456789012` and `1234-5678-9012`.
- **FR-002**: The check MUST report IPv4 addresses, except the documentation ranges of
  RFC 5737, loopback, the unspecified and broadcast addresses, and the cloud metadata
  address `169.254.169.254`. A dotted value with an octet above 255 is not an address.
- **FR-003**: The check MUST report chat-platform IDs (a type letter, a digit, then seven to
  nine upper-case letters or digits).
- **FR-004**: The check MUST report ticket keys (an upper-case project prefix, a hyphen and
  a number), except prefixes of standard names (ADR, RFC, CVE, SHA, UTF, ISO, FR, SC and
  the like) and values followed by a decimal part, such as licence versions.
- **FR-005**: The check MUST report hostnames under internal-only suffixes (`.internal`,
  `.corp`, `.local`, `.lan`, `.intranet`, `.consul`, `.home.arpa`), except names that are the
  same on every machine and names with a label starting with `example`.
- **FR-006**: The check MUST report cloud endpoints that name a resource (databases, load
  balancers, API gateways, buckets), except those with a label starting with `example`.
- **FR-007**: The check MUST report e-mail addresses, except GitHub's no-reply and service
  addresses and addresses under reserved domains (RFC 2606).

**Layer 2 — private deny-list**

- **FR-008**: The check MUST read the deny-list from a file in the private configuration
  directory, which is the `OPSCOUT_CONFIG` path when set and the default configuration
  directory otherwise (ADR-0014). Each non-blank, non-comment line is a case-insensitive
  pattern.
- **FR-009**: The check MUST report every match of a deny-list pattern as a `private-term`
  finding, whether or not the value is in the allow-list.
- **FR-010**: When the deny-list is missing, the check MUST warn that layer 2 was skipped and
  continue, unless the clone requires the deny-list, in which case it MUST fail and say
  where the file was expected.
- **FR-011**: When a deny-list entry is not a valid pattern, the check MUST stop with an
  error naming the entry's line, without running.
- **FR-012**: No deny-list term, and no file holding one, MAY be stored in this repository.

**Layer 3 — commit identity**

- **FR-013**: The check MUST report an author or committer address that is not a GitHub
  no-reply address (with or without the numeric prefix, including bot accounts) or
  GitHub's own no-reply address.
- **FR-014**: The identity hint MUST name the git setting to change and MUST NOT suggest the
  allow-list.

**What is checked, and when**

- **FR-015**: The check MUST examine file contents and file names (including symbolic links
  by their own name) of the files it is given, before each commit.
- **FR-016**: The check MUST examine the commit message before each commit, including
  comment lines and excluding anything below the scissors line.
- **FR-017**: The check MUST examine the identity of the commit being made, before each
  commit.
- **FR-018**: Before each push, the check MUST examine, with every layer, every local commit
  the remote does not have: its identity, its message, the names of the files it adds or
  changes, and the lines it adds.
- **FR-032**: Whenever the pre-push hooks run, the check MUST examine, with layers 1 and 2,
  the name of every branch and tag being pushed, and report a finding against the ref.
  Deleting a remote ref is not checked.
- **FR-019**: The check MUST examine a given range of commits in the same way, so CI can
  check every commit of a pull request; a range without a known base covers every commit
  reachable from its head.
- **FR-020**: The check MUST be able to examine every tracked file of the repository.
- **FR-021**: Within commits, the check MUST read file names exactly, MUST read a file that
  git treats as binary when it holds no NUL byte, MUST compare a merge with its first parent,
  and MUST ignore deletions.

**Reporting**

- **FR-022**: Each finding MUST state its location (file and line, file name, message line,
  or commit and role), its rule and the matched value, and the check MUST exit with a failure
  status when there is at least one finding.
- **FR-023**: After the findings, the check MUST print one hint for each kind of finding
  present: layer-1 patterns (one shared hint), private terms, and commit e-mail.
- **FR-024**: When run in CI, or when asked to, the check MUST redact the matched values,
  keeping at most their first two characters, wherever they appear in its output, including
  inside the file or ref name a finding is located in.

**Allow-list and pattern changes**

- **FR-025**: The allow-list MUST live in this repository, and every entry MUST carry a
  value and a non-empty reason; an entry missing either MUST stop the check with an error
  naming the entry.
- **FR-026**: An allow-listed value MUST NOT be reported by layer 1.
- **FR-027**: Every allow-list entry MUST still be matched by a layer-1 rule; an entry that
  no rule matches any more is stale and MUST fail the test suite. Beyond that, every change
  to a layer-1 pattern or to its harmless values comes with a synthetic test case that
  reproduces the miss or false positive it fixes (checked in review).

**Test suite**

- **FR-028**: The test suite MUST hold, for each layer-1 rule, at least one synthetic leak
  that is caught and at least one reserved or harmless value that passes.
- **FR-029**: Synthetic leaks MUST be assembled when the tests run, so no test file holds a
  value the check would report.
- **FR-030**: Every test of the check MUST be tied to the requirement it proves.

**Performance**

- **FR-031**: The check MUST finish in under one second on a typical change, and in time
  linear in the input on pathological lines.

### Key Entities

- **Finding**: one value that looks like real data. It has a location, the rule that matched,
  and the value (shown or redacted).
- **Rule**: a layer-1 shape and the test for the values it may match harmlessly.
- **Allow-list entry**: a value that a layer-1 rule matches but that is not real data, with
  the reason. Public.
- **Deny-list entry**: a private, case-insensitive pattern for a term that must never appear.
  Private; never in this repository.
- **Check run**: one invocation over files, tracked files, a message, the identity, a commit
  range or the commits being pushed.

## Non-Goals

- **Secret detection.** Tokens, keys and passwords are gitleaks' job (ADR-0015); this check
  does not duplicate it.
- **Other repositories.** The check guards this repository only; it does not scan the
  private configuration repository or the user's other projects.
- **Publishing the deny-list.** The check never stores deny-list terms in this repository,
  never sends them anywhere, and never runs layer 2 in CI.
- **Fixing or rewriting.** The check reports; it never edits files, rewrites messages or
  rewrites history. A leak that reached the public history is an incident, not something the
  check repairs.
- **Network access.** The check runs offline and reads only local files and the local git
  repository.
- **IPv6 addresses and other shapes not listed in FR-001 to FR-007.** Decided on
  2026-11-03: they are added only when a real miss justifies them (FR-027).
- **Allow-listing private terms or identities.** Neither layer 2 nor layer 3 can be excused
  through the allow-list.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of the synthetic leaks in the test suite are caught, in every place each
  can appear (file contents, file names, commit messages, commit ranges).
- **SC-002**: 0 findings on the repository's own tracked files at the head of `main`.
- **SC-003**: A contributor waits under one second for the check on a typical change
  (20 files, 1,000 added lines), measured end to end, start-up included (0.31 s for every
  tracked file on 2026-11-03); a pathological 32,000-character line takes under two
  seconds.
- **SC-004**: 0 deny-list terms in this repository's files or history, and 0 matched values
  in CI logs.
- **SC-005**: 100 % of the functional requirements are covered by at least one test tied to
  them.
- **SC-006**: 100 % of allow-list entries carry a reason.

## Assumptions

- Contributors set up their clone with `uv run just setup`, which installs the pre-commit,
  commit-msg and pre-push hooks (CONTRIBUTING.md). A clone without the hooks is caught by
  CI.
- CI runs layers 1 and 3. It cannot run layer 2, because the deny-list is private
  (ADR-0015).
- "Typical change" means up to 20 files and 1,000 added lines, the size of a normal pull
  request in this repository.
- The default configuration directory is the one ADR-0014 defines; the configuration
  contract spec may later move the deny-list's location, and this spec follows it.
- Shapes are tuned for the platforms named in ADR-0005 (AWS account IDs, Slack IDs, Jira
  keys); other platforms' shapes are added when an adapter for them exists.
- The existing implementation from Phase 0a is the starting point; this feature changes it
  only where a requirement is unmet.
