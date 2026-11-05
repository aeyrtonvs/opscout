# Data model: SSO check hook

## Sso (the `sso` section; optional)

| Field | Type | Default | Rule |
|---|---|---|---|
| `enabled` | boolean | `true` | `false` turns the check off |
| `sessions` | list of names, or absent | absent: every SSO session and older SSO profile in the AWS config | 1–50 names, unique; each 1–100 characters, no whitespace or control characters |

## SsoSession

| Field | Type | Meaning |
|---|---|---|
| `name` | text | the SSO session's name, or the older profile's name |
| `kind` | `sso-session` or `profile` | decides the login command (`--sso-session` or `--profile`) |
| `cache_key` | text | SHA-1 hex of the session name, or of the profile's start URL |

## SessionCheck

| Field | Type | Meaning |
|---|---|---|
| `name`, `kind` | as above | `kind` is absent for an unknown name |
| `state` | `valid`, `expired`, `not-logged-in`, `unreadable`, `unknown` | R3 |
| `expires_at` | UTC time or absent | for `valid` and `expired` |
| `reason` | text or absent | for `unreadable`: what is wrong, never a value |

A check needs a login unless its state is `valid`.
