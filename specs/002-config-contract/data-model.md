# Data model: Configuration contract

No storage: the configuration is read on each use. Names match `opscout.core.config`.

## Configuration (version 1)

The validated content of `config.yaml`. Frozen; unknown keys are rejected at any depth;
values are never coerced (FR-014, FR-015, FR-032).

| Field | Type | Rule |
|---|---|---|
| `schema_version` | integer, `const: 1` | required; checked before anything else (FR-011 to FR-013) |

Later specs add optional sections; each addition keeps version 1 and adds a configuration
to the compatibility set (FR-029, FR-030).

## KeychainRef

The only way a section may name a credential (FR-019). Not used by version 1 itself; it
is the type later sections use, and FR-020's test enforces it.

| Field | Type | Rule |
|---|---|---|
| `service` | text | required; 1–128 characters, no whitespace or control characters |
| `account` | text or absent | optional; same shape as `service` |

## Problem

| Field | Type | Rule |
|---|---|---|
| `file` | text | the path as given to the loader |
| `line` | integer ≥ 1 | 1-based |
| `column` | integer ≥ 1 | 1-based |
| `path` | text | dotted key path with `[n]` for items, or `(top level)` |
| `message` | text | never contains the value found (FR-017) |

Problems are ordered by `line`, then `column` (FR-016).

## Configuration source

| Value | When |
|---|---|
| `--config` | the directory was given on the command line |
| `OPSCOUT_CONFIG` | the variable is set and not empty |
| `default` | `~/.config/opscout/` |

## Version constants

| Name | Value | Meaning |
|---|---|---|
| `SCHEMA_VERSION` | `1` | the only major version this engine reads |
| `RETIRED_VERSIONS` | `{}` | retired major version → anchor of its migration note in `docs/reference/configuration.md` |

## Limits

| Limit | Value | Requirement |
|---|---|---|
| file size | 1 MiB | FR-005 |
| nodes, aliases expanded | 10,000 | FR-010 |
