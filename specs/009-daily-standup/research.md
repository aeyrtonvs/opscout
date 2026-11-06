# Research: Daily standup

Checked on 2026-11-05 against the maintainer's local Claude Code transcripts (structure only;
no content was read into this repository), Atlassian's Bitbucket Cloud documentation, and
specs 007 and 008.

## R1. Session transcripts (FR-004)

**Facts** (Claude Code 2.1.318, 167 local transcripts, field names only): one JSON Lines
file per session under `<claude config dir>/projects/<encoded directory>/<session>.jsonl`.
Each line has a `type`; `user` lines carry `cwd`, `sessionId`, `timestamp`, `gitBranch`,
`isMeta`, `isCompactSummary`, `promptSource` (`typed`, `suggestion_accepted`, `queued`,
`system`, …), `toolUseResult` (on tool results) and `message.content` (a string, or a list
of blocks of type `text` or `tool_result`). Many lines are not prompts: tool results (by
far the most), `isMeta` lines, compact summaries, and strings that start with
`<task-notification`, `<local-command-`, `<command-name`, `<bash-input`, `<bash-stdout`,
`<system-reminder`; pasted text arrives inside `<pasted_content …>` tags. Other types
(`assistant`, `system`, `ai-title`, `attachment`, …) are never prompts.

**Decision**: a prompt is a `user` line whose `isMeta`, `isCompactSummary` and
`toolUseResult` are absent or false, whose `promptSource` is not `system`, and whose
content is a string or `text` blocks with none of the markers above. From it, pasted blocks
(`<pasted_content…>…</pasted_content>`) and any other `<tag>…</tag>` block are removed
before shortening, since pasted text is where alerts and secrets land. The session's
project is the configured project whose path contains `cwd` (the longest match); sessions
outside every project are not read further. Only lines with `timestamp` in the window
count. The adapter reads files whose modification time is inside or after the window, line
by line, and skips a line it cannot parse (counted). The rules are pinned by contract tests
on hand-written, sanitized samples that follow these shapes; a change of format shows as
"some sessions could not be read", never as a guess.

## R2. Commits from local clones (FR-005)

**Decision**: per configured path, one read-only command:
`git -C <path> log --all --source --no-merges --author=<identity>… --since=<start>
--until=<end> --format=%H%x1f%aI%x1f%S%x1f%s` (each identity as its own `--author`, which
git ORs). `%S` is the ref the commit was reached from; each hash appears once. The program
is found with `shutil.which("git")`; the environment is the job's, with
`GIT_CONFIG_NOSYSTEM=1` and no pager. A path that is not a repository, or a git error, makes
that path's source missing (FR-008). Subjects only, never bodies or diffs.

## R3. Pull requests from Bitbucket Cloud (FR-006, FR-021)

**Facts**: app passwords were retired in 2026; the replacement is an API token with
scopes, used with HTTP Basic authentication (the account's e-mail or username and the
token). Reading pull requests needs `read:pullrequest:bitbucket`, and repository reads need
`read:repository:bitbucket` (not implied by the first). The pull request list takes a `q`
filter on `author.uuid`, `reviewers.uuid` and `state`; the list's default representation
omits participants, which `fields=+values.participants` adds. A participant has `user`,
`role` (`PARTICIPANT` or `REVIEWER`), `approved`, `state` (`approved`,
`changes_requested`, or null) and `participated_on`.

**Decision**: with `https://api.bitbucket.org/2.0`, stdlib `urllib` and spec 008's
`truststore` context (no new dependency):

1. `GET /user` once, for the token owner's `uuid`. **Confirmed live (2026-11-05)**: with
   only the two read scopes, the repository and pull request endpoints answer 200 and
   `/user` answers 403 ("Your credentials lack one or more required privilege scopes"); it
   needs `read:user:bitbucket` (Atlassian's API reference; `read:account` does not do), so
   the token needs three scopes, and a 403 names the one missing. A 404 (a repository gone, moved, or out of the token's
   reach) fails only that repository. Live, 24 repositories took about 47 s of the 60 s
   budget per source. The budget counts every request from the first, and a source that
   runs out keeps what it read and is named missing. A pull request list gives no closing
   time, so "merged or declined in the window" means its last update falls in the window
   (independent review, M5).
2. Per configured repository `<workspace>/<slug>`, three queries (paginated, at most 5 pages
   each):
   `GET /repositories/<workspace>/<slug>/pullrequests?q=author.uuid="<uuid>" AND
   updated_on>=<window start>&state=MERGED&state=DECLINED&fields=…` for the user's pull
   requests closed in the window; `…?q=author.uuid="<uuid>" AND state="OPEN"&fields=…` for
   **all** their open pull requests, with no date filter, since an old one with no activity
   is exactly a blocker (analysis A1); and
   `…?q=reviewers.uuid="<uuid>" AND state="OPEN"` for reviews waiting on the user.
3. For each open pull request of the user whose participants show `changes_requested`:
   `GET …/pullrequests/<id>/commits` and `…/comments?q=user.uuid="<uuid>"`, to see whether
   the user pushed or replied after the request (FR-021).

Facts keep the title (redacted), state, times, branch names, the review summary and the
link; never descriptions, diffs or comments' text. Errors map like spec 008's (401/403: the
token is rejected or lacks a scope, named; 429: wait as asked; other: the source is
missing). Each request has a 20-second timeout, and each source 60 seconds in all; past
that, the source is missing, so a slow host cannot hold the daily (analysis A4). The token is resolved through the secret store
(`bitbucket_token`) and never leaves the adapter.

**Blocker rule (FR-021)**: an open pull request of the user is a blocker when no
participant has `approved: true` and at least one full working day (by the job's weekdays)
lies between its `created_on` and now; or when a participant's state is
`changes_requested` and the user has a commit or a comment after that participant's
`participated_on`. The rule is code in `services/standup.py`, tested on fixed clocks.

## R4. The window (FR-003)

**Decision**: with `now` the start time and the job's weekdays, the previous working day is
the latest day before today whose weekday is in the job's weekdays; the window is
`[that day 00:00, today 00:00)` in local time. The days covered are listed in the message
("Thursday 5 to Sunday 8"). "Today" uses the state at `now`.

## R5. Minimization (FR-007)

**Decision**: per fact type, fixed caps, all configurable in `standup.limits`: a prompt
shortened to 300 characters at a word boundary with `…`; at most 20 prompts per session
(the first 10 and the last 10); at most 40 commits, 30 pull request facts and 60 prompts in
all; everything cut is counted and given to the model as counts ("12 more prompts"). Facts
are ordered by project, then time; duplicates (the same commit through two paths) go once.
Fact identifiers are short and stable within a run: `s1`… (sessions), `c1`… (commits), `p1`…
(pull requests), `r1`… (reviews waiting).

## R6. Redaction (FR-009)

**Decision**: `services/redact.py`, pure, applied to every text that reaches the model
(prompts, commit subjects, pull request titles, branch names), in this order, each match
replaced by `[<kind>]`:

| Kind | Matches |
|---|---|
| `private-key` | `-----BEGIN … PRIVATE KEY-----` … `-----END … PRIVATE KEY-----` |
| `credential` | known token shapes: `AKIA…`/`ASIA…` (AWS), `xox[abpr]-…`, `xapp-…`, `ghp_…`, `github_pat_…`, `glpat-…`, `sk-…` (20+ characters), JWTs (`eyJ….eyJ….…`), `ATATT…` (Atlassian) |
| `credential` | `<name>=<value>` or `<name>: <value>` where the name contains password, passwd, secret, token, api_key, apikey, access_key or private_key |
| `connection-string` | `<scheme>://<user>:<password>@…` |
| `email` | addresses |
| `phone` | `+` or a digit, then 8 or more digits with spaces, dots, dashes or parentheses |
| `account-id` | 12 digits standing alone |
| `ip` | IPv4 addresses |
| `deny-listed` | every term of `standup.redact` (case-insensitive, anywhere, words joined by spaces, hyphens, underscores or nothing; also in project names) |
| `secret-like` | any other run of 32 or more characters from the base64 or hex alphabets |

The run record gets the counts by kind. A corpus test plants every kind in every source
(prompts, subjects, titles, branches) and searches the model input and the record for the
planted values (SC-004). The deny-list is configuration (the engine reads only
`config.yaml`, spec 002, so the leak check's private deny-list file is not read).

## R7. Prompt, output and checks (FR-010, FR-011, FR-015)

**Decision**:

- The prompt is fixed text plus one block:
  `<facts untrusted="true"> … </facts>`, with each fact as a line
  `[<id>] <project> <time> <source>: <text>`, and the counts of what was cut. The prompt
  says the block is data written partly by other people, that instructions inside it are
  text, and that every output line must cite fact ids.
- The output model `StandupOutput`: `yesterday` (1–8 items of `project`, `text` ≤ 200
  characters, `facts` ≥ 1), `today` (0–8 items of `text`, `facts`), `blockers` (items of
  `text`, `facts`), `note` (optional, ≤ 200). Its validators take the run's facts as
  pydantic validation context and refuse: an unknown fact id; a project not configured, or
  with no fact; a blocker citing a fact not marked as a blocker; a marked blocker no
  blocker line cites; more than six yesterday lines, or fewer than three when there are at
  least three yesterday facts.
- spec 007's runner validates with that context, so a refusal follows its convergence (one
  retry with the validator's message, then `inconclusive`). `RunProfile` gains
  `validation_context`; the runner passes it to `model_validate`.
- The engine renders the message: a heading with the days covered, three sections, each
  line followed by nothing of the facts. Slack writes mentions, channel-wide alerts and
  links as `<…>` (`<@U…>`, `<!channel>`, `<https://…|…>`); the render breaks that syntax in
  any text from facts or from the model (`<` and `>` become `‹` and `›`) and leaves a plain
  `@` alone, which notifies no one (FR-012). Spec 008 sends a `markdown` block, which also
  makes `[text](url)`, `![alt](url)` and a bare `https://…` live links (found in
  convergence): the render turns `[` and `]` into full-width brackets and `://` into
  `:∕∕`, so none of them is a link. The live check (T034) plants a `<!channel>` and
  a `<@…>` in a fact and confirms they show as text in the `markdown` block (analysis A2).
- The job's default profile: no tools, model `sonnet`, budget 0.10 USD, 3 turns; the
  evaluation run (R9) decides whether `haiku` suffices, and the default follows it.
  **Result (2026-11-05)**: the first `sonnet` run passed 7 of 8 cases (0.096 USD): asked to
  ignore planted instructions, it did, but quoted the planted word in its note (3 of 5
  repeats). The prompt now forbids quoting or repeating such an instruction; then 6 of 6
  repeats were clean and the suite passed 8 of 8 with `sonnet` (0.088 USD, about 0.02 USD
  for an ordinary day) and with `haiku` (0.007 USD). Per the spec's assumption (the smallest
  model that passes the suite), the default is now `haiku`. The code graders check format,
  citations and safety, not the writing, so the week of agreement (SC-002) is where it is
  judged; a user who disagrees sets `jobs.standup.model: sonnet`. The live daily the user
  agreed with ran on `sonnet` (0.025 USD).

## R8. Fitting the job into spec 007 (FR-016, FR-017)

**Decision**: `Start` gains `prepare: Callable[[datetime], Preparation] | None`, called by
`run_job` after the lock and the "already delivered?" check, so a skipped start gathers
nothing. A `Preparation` holds either a model run (`prompt`, `validation_context`,
`render`, `inputs`) or a ready text (no activity, FR-016: delivered without the model,
`runner` null). Gathering errors of one source become a "missing" note; an exception in
`prepare` itself ends the start as `failed` with its type. The record's `inputs` hold the
references (FR-013): `sessions:4 prompts:31 cut:6 commits:9 prs:5 reviews:2
redactions:email=2,credential=1 missing:bitbucket`.

## R9. Evaluations (FR-018)

**Decision**: synthetic histories in `evals/standup/<case>/` (a ready fact list plus the
expected checks), with fake projects (`example-api`, `example-web`) and planted values:
`ordinary-tuesday`, `monday-covers-weekend`, `quiet-day`, `bitbucket-missing`,
`planted-secrets`, `planted-instructions`, `large-day`, `stale-review-blocker`. In the test
suite each case runs through the real prompt and checks with a fake runner (structure and
graders). `tools/standup_evals.py` runs them through `ClaudeCliRunner` with the user's
login, on demand, with a total cost ceiling (default 0.50 USD), grading in code (schema,
citations, projects, blockers, planted values absent, format kept) and printing a table
with cost; the result is recorded in the spec's Actuals. No LLM judge.

## R10. Configuration (FR-001, FR-002)

**Decision**: a top-level optional `standup` section:

```yaml
standup:
  identities: [dev@example.com]                 # commit authors, e-mail or name
  code_host:
    service: bitbucket
    login: dev@example.com                      # Basic auth user; the token is a secret
  projects:
    example-api:
      paths: [/Users/example/src/example-api]
      repositories: [example-workspace/example-api]
  redact: [Example Corp]                        # extra terms, case-insensitive
  limits: {prompt_length: 300}                  # optional overrides
```

with `daemon.secrets.bitbucket_token` (a new keychain item) and the job `standup` in
`daemon.jobs` (`at`, weekdays, limits as spec 007). `JOB_NAMES` gains `standup`. The job
needs the `standup` section; a `code_host` needs `bitbucket_token`; validation refuses
relative paths, duplicate projects, a project with neither paths nor repositories, and a
repository not written `<workspace>/<slug>`.

## R12. Projects from folders (FR-023; asked during the live check)

**Decision**: `standup.folders` lists absolute folders. The `Commits` adapter discovers, per
folder, every directory that holds `.git`, at most three levels down, not descending into a
repository once found and skipping hidden directories, `node_modules` and `vendor`; for each
it reads `git remote get-url origin` (read only) and keeps `<workspace>/<slug>` when the URL
is on `bitbucket.org`. The project's name is the directory's name in lowercase with any run
of other characters turned into a hyphen (prefixed `repo-` when it would start with a digit);
repositories with the same name join one project with all their paths; an explicit project
of the same name replaces the discovered one. Discovery runs at each start, so a new clone
is picked up without editing the configuration.

## R11. Live check (FR-020, the plan's exit criteria)

**Decision**: in the implementation, with the user's own projects in a temporary copy of
the configuration: gather a real window and show only counts and redaction kinds (never the
text) to confirm the transcript and git rules; confirm Bitbucket's endpoints, scopes and
fields with a token the user creates and stores themself; run the evaluation suite with the
user's model; deliver one real summary by DM and let the user judge it. A week of dailies
and the agreement rate are measured after merge and recorded in PLAN.md (FR-020).
