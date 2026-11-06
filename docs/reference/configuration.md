# Configuration reference

opscout reads every organization-specific fact from **your private configuration**, never
from this public repository (ADR-0002). This page is the contract between the two:
where the configuration is found, what the file may hold, and how it changes over time
(ADR-0014, [spec 002](../../specs/002-config-contract/spec.md)).

## Where it is found

The configuration directory is the first of:

1. the `--config DIR` option;
2. the `OPSCOUT_CONFIG` environment variable, when it is set and not empty;
3. `~/.config/opscout/`.

A leading `~` is expanded in both the option and the variable. Inside Claude Code, the
plugin asks for the directory when it is installed.

The configuration is the file `config.yaml` in that directory. Nothing else there is read
by the loader; the directory may also hold the leak check's private deny-list
(`leak-denylist.txt`) or anything else of yours.

## Checking it

```sh
opscout config validate [--config DIR]
```

It prints the directory and where it came from, then either `valid (schema version 1)` or
one line per problem, in file order:

```text
<file>:<line>:<column>: <key path>: <message>
```

Every problem in the file is listed in one run. A message names the key, what was
expected and where; it never repeats the value found, so the output is safe to paste or to
keep in a CI log. The exit status is 0 when the configuration is valid, 1 when it is
invalid or cannot be found or read, and 2 on bad arguments.

To validate a private repository on every commit, add the hook this repository publishes:

```yaml
repos:
  - repo: https://github.com/aeyrtonvs/opscout
    rev: <commit>
    hooks:
      - id: opscout-config-validate
```

It validates the repository it runs in, whatever `OPSCOUT_CONFIG` says.

## The file

- UTF-8 YAML (a byte-order mark is allowed), at most 1 MiB, one document whose top level is
  a mapping.
- Plain data only: mappings, sequences, and string, integer, float, boolean, null and
  date scalars. Other tags (such as `!!python/object` or `!!binary`) and the merge key
  `<<` are refused, and reading never runs code.
- Every key is a string, and no key appears twice in a mapping. `1:`, `true:`, `~:` and
  `2001-01-01:` are not string keys; quote them if you mean text.
- Aliases are allowed, up to 10,000 nodes once expanded and 100 levels of nesting.
- No value is converted to another type: `"1"` is a string, `1.0` a number, `true` a
  boolean. Write integers without a decimal point: `3.0` is refused where an integer is
  expected, although some editors accept it.
- Values mean the same to opscout and to an editor that follows YAML 1.2: an integer is
  written in plain decimal (`10`, not `0x0a`, `1_0` or `010`), and a boolean as `true` or
  `false` (`yes`, `no`, `on` and `off` are refused; quote them for text).
- Every key must be known. A key opscout does not know is a problem: a typo, or a key from
  a newer opscout. In messages, a key that is empty or not plain text is shown quoted and
  escaped.

The models in `src/opscout/core/config.py` are the source of truth. Their JSON Schema is
committed at [`schemas/config.schema.json`](../../schemas/config.schema.json), so editors
can validate the file while you write it: start the file with

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/aeyrtonvs/opscout/<commit>/schemas/config.schema.json
```

`opscout config schema` prints the same schema.

## Schema version 1

| Key | Required | Type | Meaning |
|---|---|---|---|
| `schema_version` | yes | integer, exactly `1` | the major version of the schema the file follows |

Each feature that needs configuration adds its own section, in its own spec, as an additive
change. [`example-config/`](../../example-config/) is a complete, valid example.

### `writeups` (optional; spec 003)

Write-up formats for the summary skill. Without the section, the built-in `ticket`,
`message` and `postmortem` formats apply.

| Key | Type | Meaning |
|---|---|---|
| `language` | text, up to 40 characters | the language to write in; without it, the language you write in |
| `rules` | list of up to 30 lines | rules for every format, after the built-in ones |
| `formats` | mapping of name → format | a built-in name replaces that format; a new name adds one |

A format name is lowercase words joined by hyphens (`status-update`), up to 40 characters.
A format holds:

| Key | Required | Type | Meaning |
|---|---|---|---|
| `description` | yes | one line, up to 200 characters | what the format is for |
| `sections` | no | list of up to 30 lines | the headings, in order; none for free text |
| `rules` | no | list of up to 30 lines | rules for this format only |
| `max_lines` | no | integer, 1–200 | the most lines a write-up may have |

Whatever the configuration says, every write-up states only facts from the session, never
lists what was evaluated and ruled out nor how the result was reached, and never holds a
secret value. `opscout writeup formats [--config DIR]` prints the formats the skill uses.

### `ship` (optional; spec 004)

Conventions for the ship skill and the plugin's push guard.

| Key | Default | Meaning |
|---|---|---|
| `protected_branches` | `[main, master]` | branch patterns (globs such as `release/*`) that are never pushed to; `main`, `master` and the remote's default branch are protected whatever the list says |
| `branch_pattern` | `{type}/{slug}` | how new branches are named; tokens `{type}`, `{slug}` (required) and `{ticket}` |
| `types` | the Conventional Commit types | the types allowed in commit messages and branch names |
| `trailer` | `Assisted-by: Claude Code` | the last line of every commit message the skill writes |
| `pull_request.base` | the remote's default branch | the branch pull requests target |
| `pull_request.draft` | `true` | pull requests are always drafts; `false` is refused |

With the plugin enabled, a hook asks before every `git push` and `gh pr create` Claude runs,
and refuses a push to a protected branch, whatever your own permission settings say. It
reads only the plain form, `git [-C <dir>] push [<options>] [<remote> [<branch>...]]`, and
refuses a push written any other way. `opscout ship rules`, `opscout ship check-branch` and
`opscout ship check-message` print and check the conventions.

### `sso` (optional; spec 005)

The SSO check at the start of a Claude Code session.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | whether the check runs when a session starts, resumes, is cleared or is forked |
| `sessions` | every SSO session and older SSO profile in the AWS config | the logins to check, by name: an SSO session's name, or a profile's (a profile on an SSO session stands for that session); 1–50 unique names |

With the plugin enabled, a SessionStart hook reads the AWS config (`AWS_CONFIG_FILE`, or
`~/.aws/config`) and the AWS CLI's token cache (`~/.aws/sso/cache/`), and tells you and
Claude which logins have expired, were never made or could not be checked, with the
`aws sso login` command for each. It says nothing when every login is valid. It never uses
the network, never logs in and never shows a token: it takes only each token's expiry. An
expired token counts as expired even when the AWS CLI might renew it. `opscout sso check`
prints every checked login's state and exits 1 when one needs a login.

### `personal_context` (optional; spec 006)

The facts every Claude Code session should start with. `opscout context apply` writes them
into a marked block of Claude Code's `CLAUDE.md` (in `CLAUDE_CONFIG_DIR`, or `~/.claude`).

| Key | Type | Meaning |
|---|---|---|
| `language` | one line, up to 40 characters | the language Claude answers you in |
| `timezone` | an IANA time zone name, such as `Europe/Lisbon` | your time zone |
| `sections` | mapping of heading → list of lines | headings, in order, each with up to 50 lines of up to 300 characters; up to 20 headings of up to 60 characters, without `#` |

At least one key is present, and no value holds a line break or `opscout:personal-context`.

- `opscout context show` prints the block.
- `opscout context diff [--target FILE]` shows the change as a unified diff and prints a
  confirmation code; it never writes.
- `opscout context apply [--target FILE]` asks before writing in a terminal; elsewhere it
  writes only with `--confirm <code>` from a diff, and only while the file and the
  configuration still give that diff.

Only the lines between the markers change; everything else in the file stays as you wrote
it. Applying again changes nothing. To remove the block, delete it by hand.

### `daemon` (optional; spec 007)

Scheduled jobs, the Claude Code executable they use, and the harness's own secrets. The
engine defines the jobs; this section schedules them and may lower or raise their limits.

```yaml
daemon:
  jobs:
    check:
      at: "09:30"
      weekdays: [mon, tue, wed, thu, fri]
  claude_path: /opt/example/bin/claude
  secrets:
    claude_token:
      service: opscout-example
```

| Key | Default | Meaning |
|---|---|---|
| `jobs` | none | the jobs to schedule, by name; the engine knows `check` |
| `jobs.<name>.enabled` | `true` | whether `opscout daemon install` schedules the job |
| `jobs.<name>.at` | required | the time of day, `HH:MM` from `00:00` to `23:59`, in the machine's local time; quote it |
| `jobs.<name>.weekdays` | every day | the days it runs: 1–7 unique values from `mon` to `sun` |
| `jobs.<name>.model` | the job's own (`haiku` for `check`) | an alias (`haiku`, `sonnet`, `opus`, `fable`) or a full `claude-…` id |
| `jobs.<name>.budget_usd` | the job's own (0.05 for `check`) | the most one run may cost, above 0 and at most 5 |
| `jobs.<name>.max_turns` | the job's own (3 for `check`) | the most turns one run may take, 1–50 |
| `claude_path` | `claude` on `PATH` | the Claude Code executable, as an absolute path |
| `secrets` | none | keychain references by name: `claude_token`, a token from `claude setup-token` for jobs that cannot use your login; `slack_bot_token` and `slack_app_token`, the chat app's tokens (spec 008) |
| `chat.service` | none | `slack`, the only chat service (spec 008) |
| `chat.user` | none | your Slack member id, `U` or `W` then 2–20 capital letters or digits; deliveries go to it by direct message, and only its clicks count |

`chat` needs both Slack tokens in `secrets`. With it, every delivery also goes to you as a
direct message, each result asks whether you agree, and `opscout daemon install` installs
the gateway that receives your answers.

`opscout daemon install` schedules the enabled jobs, and `opscout secret set claude_token`
stores the token; [daemon.md](daemon.md) covers the commands, the files and the outcomes.

## Rules for every section

These hold for each section a later spec adds. Review checks them; tests enforce the
parts marked *tested*.

- **Additive change**: a new optional key or section keeps the schema version, and adds a
  configuration that uses it to the compatibility set in `tests/unit/config_contract/compat/`
  (*tested*: every configuration there must still validate).
- **Breaking change**: removing, renaming or retyping a key, or making one required, raises
  the major version, moves the old version to `RETIRED_VERSIONS` and adds its migration
  note below (*tested*: a retired version without a note fails the suite).
- **No secret values**: a credential is a keychain reference, `{service: <name>, account:
  <name>}` with `account` optional, naming where the OS keychain stores it. A key whose
  name contains `token`, `password`, `passwd`, `secret`, `api_key`, `apikey`,
  `credential` or `private_key` must be a keychain reference (*tested*).
- **Descriptions**: every key has one, which editors show (*tested*).
- **Strict and read-only**: unknown keys are refused, values are never converted, and the
  loaded configuration cannot be changed.

A configuration for another major version gets one message: upgrade opscout if the file
is newer, or follow the migration note if it is older.

## Migration notes

None yet: schema version 1 is the first. Each retired version gets a section here, such as
`### From version 1`, saying what changed and how to update a configuration.
