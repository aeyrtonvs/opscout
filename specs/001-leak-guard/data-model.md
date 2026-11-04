# Data model: Leak guard

No storage: every entity lives for one run of the check. Names match `tools/leak_check.py`.

## Finding

One value that looks like real data.

| Field | Type | Rule |
|---|---|---|
| `location` | text | `path:line`, `path (file name)`, `path:line` of a message, `commit <sha12> <role>`, `commit <sha12> <path>:<line>`, or `ref <name>` (FR-022, FR-032) |
| `rule` | text | a layer-1 rule name, `private-term` (layer 2) or `commit-e-mail` (layer 3) |
| `value` | text | the matched text; rendered as its first two characters and `… (redacted)` in CI or with `--redact` (FR-024) |

## Rule (layer 1)

| Field | Type | Rule |
|---|---|---|
| `name` | text | `account-id`, `ip-address`, `chat-id`, `ticket-key`, `hostname`, `cloud-endpoint`, `e-mail` (FR-001 to FR-007) |
| `pattern` | regular expression | bounded repetition, so a line is scanned in linear time (FR-031) |
| `harmless` | predicate | true for reserved and harmless values of that shape |

Two rules may share a name (`account-id` has a plain and a dashed form).

## Allow-list entry (public, `tools/leak_allowlist.toml`)

| Field | Type | Rule |
|---|---|---|
| `value` | non-empty text | matched exactly against a layer-1 finding's value (FR-026) |
| `reason` | non-empty text | why the value is not real data (FR-025) |

Applies to layer 1 only; never to layer 2 or 3 (FR-009, FR-014).

## Deny-list entry (private, `<config dir>/leak-denylist.txt`)

One case-insensitive regular expression per non-blank line; lines starting with `#` are
comments (FR-008). An invalid entry stops the run and names its line (FR-011). The file
never exists in this repository (FR-012).

## Check run

| Mode | Input | Layers | Gate |
|---|---|---|---|
| `files PATH…` | whole files and their names | 1, 2 | pre-commit (FR-015) |
| `tracked` | every tracked file | 1, 2 | on demand (FR-020) |
| `message FILE` | a commit message, above the scissors line | 1, 2 | commit-msg (FR-016) |
| `identity` | the author and committer of the commit being made | 3 | pre-commit (FR-017) |
| `commits [BASE] HEAD` | each commit of the range | 1, 3 (and 2 when present) | CI (FR-019) |
| `pushed` | each commit the remote lacks, and the names of the pushed and local refs | 1, 2, 3 | pre-push (FR-018, FR-032) |

States: a run either passes (exit 0), finds something (exit 1), or cannot start because of
an invalid allow-list or deny-list, or a missing deny-list the clone requires (exit 1 or 2,
with the reason on standard error).
