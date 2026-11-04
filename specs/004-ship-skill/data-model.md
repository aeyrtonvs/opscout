# Data model: Ship skill

## Ship (the `ship` section; optional)

| Field | Type | Default | Rule |
|---|---|---|---|
| `protected_branches` | list of globs | `[main, master]` | 1–100 characters each, at most 30; `main`, `master` and the remote's default branch are protected whatever the list says |
| `branch_pattern` | text | `{type}/{slug}` | must contain `{slug}`; only the tokens `{type}`, `{slug}`, `{ticket}`; otherwise `[a-z0-9/._-]` |
| `types` | list of words | the Conventional Commit types | lowercase letters, at most 20 |
| `trailer` | text | `Assisted-by: Claude Code` | `Key: value`, one line, up to 100 characters |
| `pull_request.base` | branch name or absent | the remote's default branch | |
| `pull_request.draft` | `true` | `true` | `false` is refused |

## PushDecision

| Field | Type | Meaning |
|---|---|---|
| `verdict` | `ask`, `deny` or none | none: the command is not the guard's business |
| `reason` | text | shown to the user (ask) or to Claude (deny) |
