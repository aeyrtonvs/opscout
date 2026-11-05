# Research: SSO check hook

Facts were checked on 2026-11-04 against the Claude Code hooks reference, the botocore
source bundled with the AWS CLI 2.27.5, and the maintainer's machine (key names and counts
only; no value was printed).

## R1. How does a plugin's SessionStart hook speak, and how does it fail? (FR-001 to FR-003)

**Facts**:

- SessionStart matchers: `startup`, `resume`, `clear`, `compact`, `fork`. Plugin hooks support
  SessionStart with `type: "command"`.
- `hookSpecificOutput.additionalContext` "adds context at the start of the conversation";
  `systemMessage` is a "warning message shown to the user", and the SessionStart section uses
  it. Plain stdout on exit 0 is also added as context. Each string is capped at 10,000
  characters.
- SessionStart cannot block: exit 2 shows stderr to the user as a hook error, and any other
  non-zero exit is a non-blocking error. Claude's first response waits for SessionStart
  hooks. The default timeout of a command hook is 600 s.

**Decision**: `hooks/hooks.json` gains a `SessionStart` entry, matcher
`startup|resume|clear|fork`, that runs `"${CLAUDE_PLUGIN_ROOT}/bin/opscout" hook
session-start` in exec form, with `timeout: 10`. No `onFailure`: there is nothing to block.
When a login is needed, the command prints one JSON object with `systemMessage` and
`hookSpecificOutput.additionalContext` holding the same text; otherwise it prints nothing.
It always exits 0; an error becomes a `systemMessage` saying the SSO check could not run and
why (FR-003). The configuration directory comes from `CLAUDE_PLUGIN_OPTION_CONFIG_DIR`, as
for the push guard (spec 004, R1). The launcher passes this hook straight to the engine; an
installed plugin before the first release prints the launcher's own message and exits 1,
which Claude Code shows as a non-blocking hook error.

**Rejected**: `compact` (it would repeat the warning mid-session); plain stdout (the user would
not see it).

**Revised after the independent review**: the launcher runs `hook session-start` as a child
with an 8 s limit, and turns every way it can fail to start the engine (no release, no
`uvx`, a non-zero exit, the limit) into one `systemMessage`, exit 0, so FR-003 holds before
the engine runs too. Times are shown in the machine's local time for each instant, so a
daylight-saving change between now and an expiry is respected.

## R2. Where are the SSO sessions and their tokens? (FR-004, FR-005)

**Facts** (botocore `SSOTokenLoader` and `tokens.py`):

- Tokens are cached in `~/.aws/sso/cache/<key>.json`, where `<key>` is the SHA-1 hex digest of
  the SSO session's name, or of the start URL when the profile has no `sso_session`. On the
  maintainer's machine every SSO session's file was found under that name.
- botocore refuses a cached token without `accessToken` or `expiresAt` ("Token for … is
  invalid"), so such a file means a new login.
- With a refresh token, the CLI renews an access token within 15 minutes of its expiry while
  the portal session lasts; the cache does not record how long that is.
- `expiresAt` is written as `2026-11-04T18:00:00Z`; older files use
  `2026-11-04T18:00:00UTC`. Client registration files share the directory under other names.
- The AWS config file is `AWS_CONFIG_FILE` or `~/.aws/config`, in INI syntax: `[default]`,
  `[profile <name>]`, `[sso-session <name>]`.

**Decision**: the services parse the config's text with `configparser` (no interpolation,
duplicates tolerated as the CLI does, nested sub-sections ignored). **Revised after the
independent review**: a section header is split as shell words and must hold exactly a kind
and a name, as botocore's `build_profile_map` does; `AWS_CONFIG_FILE` has variables and `~`
expanded, as the CLI does; a cache file must be a regular file, opened without blocking. Every `sso-session`
section is a session; every profile with `sso_start_url` and no `sso_session` is an older
profile, listed once per start URL under its first profile's name. A config that cannot be
parsed means the check cannot run (FR-003).

## R3. States (FR-006; clarified 2026-11-04)

| Cache file | State |
|---|---|
| absent (or the cache directory absent) | not logged in |
| unreadable, above 64 KiB, not JSON, not an object | could not be checked (the reason, never the content) |
| an object without `accessToken` | not logged in (botocore refuses it) |
| `expiresAt` missing, not text, or in neither format | could not be checked |
| `expiresAt` ≤ now | expired, whatever refresh fields it holds (clarified) |
| `expiresAt` > now | valid |

A name listed in `sso.sessions` is matched against SSO session names first, then profile
names: an older profile is itself, a profile with `sso_session` stands for that session, and
anything else is unknown.

## R4. Reading without exposing (FR-007, Principle III)

The entrypoint opens each file for reading with a size limit (64 KiB for a cache file,
1 MiB for the config), decodes UTF-8 and hands the text to the services. `judge()` parses
the JSON, takes `expiresAt` and whether `accessToken` is a key, and returns a state; the
parsed object never leaves the function. Reasons name the problem (for example "not valid
JSON"), never a value; tests plant recognisable token, secret and start-URL values and
assert none appears in any output.

## R5. Timing (FR-011, SC-003; clarified 2026-11-04)

Measured on the maintainer's machine: Python start-up 10 ms, `uv run --project` 25 ms, the
launcher's own start 50 ms, and the engine's imports about 90 ms (pydantic). The whole hook
takes 160 to 200 ms, so the 100 ms target covers the check: one test times
`check_sessions()` over 20 sessions in a temporary home, 100 runs, and asserts the 95th
percentile is under 100 ms; another runs the hook through the launcher once and asserts
under 1 s, as spec 004 does.
