# Data model: Personal context

## PersonalContext (the `personal_context` section; optional)

| Field | Type | Rule |
|---|---|---|
| `language` | text or absent | one line, 1–40 characters |
| `timezone` | IANA time zone or absent | loadable by `zoneinfo`; up to 64 characters |
| `sections` | mapping heading → lines, or absent | up to 20; heading one line of 1–60 characters, not starting with `#`; 1–50 lines of 1–300 characters each |

At least one field is present. No value holds a newline or the marker text
`opscout:personal-context`.

## PendingChange

| Field | Type | Meaning |
|---|---|---|
| `target` | path | the file as named (the write goes through a link to its target) |
| `current` | bytes or absent | absent when the file does not exist |
| `new` | bytes | the current content with the block replaced or appended |
| `code` | 12 hex characters | R3 |

`changed` is true when `new` differs from `current`.
