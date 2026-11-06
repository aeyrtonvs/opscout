# Contract: commands

## `opscout run standup [--force]`

Spec 007's command and exit codes. Output lines as spec 007; the delivered text:

```text
# Standup, Thursday 5 to Sunday 8

## Yesterday
- example-api: Fixed the retry of the export job and opened its pull request.
- example-web: Reviewed the login form changes.

## Today
- Merge the export job fix once reviewed.

## Blockers
- example-api pull request "Retry export job" has waited for review since Thursday.

Sources: sessions, git, bitbucket. Bitbucket: missing (the token was rejected; store a new one with opscout secret set bitbucket_token).
```

With no activity: `No recorded activity since Thursday 5.`, then the open work, if any.

## `opscout standup preview [--counts] [--config DIR]`

Prints the window, then the facts exactly as the model would get them, then the counts:

```text
Window: Thursday 5 00:00 to Monday 9 00:00 (local time)
[s1] example-api 2026-11-05 10:02 sessions: Fix the retry of the export job … ([email] removed)
[c1] example-api 2026-11-05 11:40 git (feature/retry-export): Retry export job on 5xx
[p1] example-api 2026-11-05 11:45 bitbucket: "Retry export job" open, no approval, blocker
Counts: sessions 1, prompts 3 (cut 0), commits 1, pull requests 1, reviews waiting 0
Redactions: email 1
Missing: none
```

`--counts` prints the window and the counts only. Exit 0; 2 when the configuration has no
`standup` section or is invalid. Nothing is sent anywhere.

## `opscout secret set | check`

`bitbucket_token` is a known name.

## Evaluations

`uv run python -m tools.standup_evals [--case NAME] [--max-cost-usd 0.50]`: runs the
synthetic histories through the user's model; prints one line per case
(`pass`/`fail`, the failed check, cost) and the total; exit 1 on any failure.
