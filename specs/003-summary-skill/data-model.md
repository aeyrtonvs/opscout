# Data model: Summary skill

Names match `opscout.core.config` and `opscout.core.writeups`. Every model is strict,
frozen and refuses unknown keys, as spec 002 requires.

## Writeups (the `writeups` section; optional)

| Field | Type | Rule |
|---|---|---|
| `language` | text or absent | 1–40 characters; the language to write in (FR-002) |
| `rules` | list of text | at most 30, each 1–300 characters; apply to every format |
| `formats` | mapping name → WriteupFormat | names match `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 40 characters (FR-004) |

## WriteupFormat

| Field | Type | Rule |
|---|---|---|
| `description` | text | required, one line, 1–200 characters (FR-003) |
| `sections` | list of text | at most 30, each 1–300 characters; headings in order |
| `rules` | list of text | at most 30, each 1–300 characters |
| `max_lines` | integer or absent | 1–200 |

## Built-in formats (`BUILT_IN_FORMATS`; research R4)

`ticket`, `message`, `postmortem`. `SHARED_RULES` are the skill's contract rules and are
printed before the configured shared rules, whatever the configuration says.

## Resolved format

A WriteupFormat with its `name` and its `origin` (`built-in` or `configured`). Resolution
(FR-006): start from the built-ins; each configured format replaces the built-in of its name
or is added. Order: built-ins in their fixed order, then added formats by name.

## Formats report (the command's result)

| State | Printed |
|---|---|
| configuration read | its file, the language if set, the shared rules, every resolved format |
| directory missing | that it is missing and where it came from, then the built-in formats |
| configuration invalid | the number of problems and `opscout config validate --config <dir>`; no formats |
