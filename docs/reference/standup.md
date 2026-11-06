# Daily standup reference

The `standup` job sends you, before your daily standup, a short summary by direct message:
what you did since the last working day, by project; what is open today; and what waits on
someone else (spec 009). It is written by your own Claude Code with no tools, from facts the
engine gathers in code; every line cites its facts, and the engine refuses any line that
cites a fact it did not gather.

## What it reads, and what it never sends

| Source | What is read | Never |
|---|---|---|
| Your Claude Code sessions | your own prompts in sessions under your projects' paths, shortened | Claude's replies, tool calls and their output; pasted text; sessions outside your projects |
| Your local clones | the subjects of your commits in the window (`git log`, read only) | bodies, diffs |
| Bitbucket | your pull requests (merged, declined, open with their review state) and reviews waiting on you | descriptions, diffs, comment text |

Before anything reaches the model, secrets (keys, tokens, passwords, private keys,
connection strings), e-mail addresses, phone numbers, account ids, IP addresses, long
secret-looking strings, and every term you list in `standup.redact` are replaced by a marker
such as `[email]`. The run record keeps references only: counts, fact ids, what was cut or
redacted by kind, and missing sources.

`opscout standup preview` prints exactly what the model would get, without sending anything;
`--counts` prints the counts only. Read it once before you schedule the job.

## Setup

1. In your configuration, add the section (fake values shown):

   ```yaml
   standup:
     identities: [dev@example.com]          # your commit author e-mails or names
     code_host:
       service: bitbucket
       login: dev@example.com               # your Atlassian account e-mail
     folders: [/Users/example/src]          # every git repository inside is a project
     projects:                              # optional: group or adjust by hand
       example-api:
         paths: [/Users/example/src/example-api, /Users/example/old/example-api]
         repositories: [example-workspace/example-api]
     redact: [Example Corp]                 # names or codes never to send
   daemon:
     jobs:
       standup:
         at: "09:45"                        # 15 minutes before the standup
         weekdays: [mon, tue, wed, thu, fri]
     secrets:
       bitbucket_token:
         service: opscout-bitbucket
   ```

2. In Bitbucket, **Personal settings → Atlassian account settings → Security → API
   tokens → Create API token with scopes**, choose Bitbucket and the read scopes
   `read:pullrequest:bitbucket`, `read:repository:bitbucket` and `read:user:bitbucket`
   (the last one tells the engine who you are, to find your own pull requests), then store
   it:

   ```sh
   opscout secret set bitbucket_token
   ```

3. Check what would be sent, then run it once and judge it with the buttons:

   ```sh
   opscout standup preview
   opscout run standup --force
   ```

4. `opscout daemon install` schedules it (spec 007).

## The summary

- **Yesterday**: by project, three to six lines (fewer when there are fewer facts). On the
  first working day of the week it covers every day since the previous one, and says so.
- **Today**: your open pull requests, reviews waiting on you, and what your last sessions
  left in progress.
- **Blockers**: exactly your open pull requests that had no approval for one full working
  day, and those where a reviewer asked for changes and you answered since. The engine
  decides which; the model only words them.
- A window with nothing done says "No recorded activity since …" with the open work, and
  runs no model. A source that cannot be read is named, with the command that helps.

Mentions, channel-wide alerts and links coming from the facts are shown as plain text.

## Evaluations

`uv run python -m tools.standup_evals` runs the synthetic histories in `evals/standup/`
through your model (cost ceiling 0.50 USD by default), grading them in code: format,
citations, blockers, no planted secret, no obeyed planted instruction.
