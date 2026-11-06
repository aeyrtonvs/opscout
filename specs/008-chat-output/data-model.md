# Data model: Chat output

## Chat setting (`daemon.chat`; optional)

| Field | Type | Rule |
|---|---|---|
| `service` | `slack` | the only value |
| `user` | text | the configured user's Slack member id: `U` or `W`, then 2–20 capital letters or digits |

Present only with `daemon.secrets.slack_bot_token` and `daemon.secrets.slack_app_token`
(each a keychain reference); validation names the missing one. Example (fake id):

```yaml
daemon:
  chat:
    service: slack
    user: UEXAMPLE01
  secrets:
    slack_bot_token:
      service: opscout-slack-bot
    slack_app_token:
      service: opscout-slack-app
```

`KEYCHAIN_ITEMS` becomes `claude_token`, `slack_bot_token`, `slack_app_token`. `gateway`
is reserved: no job may take its name.

## ChatMessage (neutral; rendered by `services/chat.py`)

| Field | Meaning |
|---|---|
| `markdown` | the job's text, shortened to 11,000 characters at a line break, with the outbox note (research R3) |
| `notification` | the first line without Markdown marks, at most 150 characters |
| `buttons` | `<job>/<run-id>` for a result; none for a notice |
| `context` | `opscout <job>, run <run-id>` (the delivery knows the run, not its period), then the choice after a click |

## MessageRef

`channel` (the DM's id, `D…`) and `ts` (the message's timestamp), as Slack returns them.

## Receipt (what a delivery returns)

`location` (the outbox file) and `chat` (`MessageRef` or null).

## Agreement (in a run record)

| Field | Type | Rule |
|---|---|---|
| `choice` | `agree` or `disagree` | |
| `at` | ISO 8601 with offset | the time the click was handled |
| `reason` | text or null | `disagree` only; one paragraph, at most 500 characters, trimmed; empty is null |

## RunRecord changes (spec 007; `record_version` stays 1)

- `chat`: `MessageRef` or null: the direct message of the result or notice.
- `agreement`: `Agreement` or null (was always null).

Both are optional with null defaults, so spec 007's records still read, and a record
without them means "no chat" and "no click".

## Gateway events (neutral; from the adapter to `handle_event`)

| Event | Fields |
|---|---|
| `Choice` | `user`, `job`, `run_id`, `choice`, `ref`, `trigger` |
| `Reason` | `user`, `job`, `run_id`, `reason`, `ref` |
| `Ignored` | `kind` (only for counting) |

Transitions of a record's agreement:

```text
null → agree | disagree (click)
agree ↔ disagree (the other click)
disagree → disagree + reason (dialog submitted)
same choice and reason again → unchanged
```

## Gateway state (`<data>/gateway.json`)

`state` (`connecting`, `connected`, `stopped`), `since` (changes only with the state),
`last_seen` (updated every 60 s while the gateway runs), `reason` (a kind: `token rejected
(<code>)`, `cannot connect (<kind>)`, `asked to stop`; never a token or a message),
`handled`, `ignored`.

## ScheduledJob change (spec 007)

`keep_alive` (boolean): the gateway's entry has no times and is started at login and again
after an error exit. Its environment holds `OPSCOUT_CHAT_SETTING`, a fingerprint of the chat
setting, so a change of it reloads the gateway.

## SchedulerChange change (spec 007)

`action` gains `restart` (`launchctl kickstart -k`, for a gateway that stopped for good but
stays loaded), and a change gains a `note`: why, shown with it.
