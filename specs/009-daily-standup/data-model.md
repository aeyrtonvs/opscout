# Data model: Daily standup

## Configuration

`standup` (top-level, optional; research R10):

| Field | Type | Rule |
|---|---|---|
| `identities` | list of text | 1–10; commit author e-mails or names |
| `code_host` | object or absent | `service: bitbucket`, `login` (Basic auth user); needs `daemon.secrets.bitbucket_token` |
| `folders` | list of absolute paths | 0–10; every git repository inside (three levels) is a project (FR-023) |
| `projects` | mapping name → Project | 0–30; names like job names (lowercase words joined by hyphens); at least one folder or project |
| `redact` | list of text | 0–100 extra terms, each 2–100 characters |
| `limits` | object or absent | `prompt_length` (80–1000, default 300), `prompts_per_session` (2–100, default 20), `prompts` (10–300, default 60), `commits` (10–200, default 40), `pull_requests` (5–100, default 30) |

Project: `paths` (absolute, 0–10), `repositories` (`<workspace>/<slug>`, 0–10); at least
one of the two.

`daemon.jobs.standup`: spec 007's job settings. `daemon.secrets.bitbucket_token`: a
keychain reference (`KEYCHAIN_ITEMS` gains it). `JOB_NAMES` gains `standup`.

## Window

`start` (the previous working day, 00:00 local), `end` (today 00:00 local), `days` (the
dates covered), `now`.

## Fact

| Field | Meaning |
|---|---|
| `id` | `s<n>`, `c<n>`, `p<n>`, `r<n>`: session, commit, pull request, review waiting |
| `source` | `sessions`, `git`, `bitbucket` |
| `project` | a configured project name |
| `at` | the time (the session's first prompt, the commit, the pull request's last update) |
| `text` | minimized and redacted: prompts joined, a subject, a title with state |
| `blocker` | true for a pull request meeting FR-021 |
| `open` | true for open work (open pull requests, reviews waiting) |

## Gathered

`facts`, `cut` (counts by kind), `redactions` (counts by kind), `missing` (source → reason),
`unreadable` (sessions skipped).

## StandupOutput (the model's output; validated with the facts as context)

| Field | Rule |
|---|---|
| `yesterday` | items `{project, text ≤ 200, facts ≥ 1}`; 3–6 when there are 3 or more yesterday facts, else 1 per fact at most |
| `today` | items `{text ≤ 200, facts ≥ 1}`, at most 8 |
| `blockers` | items `{text ≤ 200, facts ≥ 1}`, citing exactly the facts marked `blocker` |
| `note` | optional, ≤ 200 |

Every cited id must exist; every project must be configured and have facts.

## Preparation (spec 007's `Start.prepare` result)

Either `Run(prompt, validation_context, render, inputs)` or `Ready(text, inputs)` (no
activity). `inputs` is the record's references (research R8).

## Run record (spec 007)

Unchanged; `inputs` now holds the references, never text.
