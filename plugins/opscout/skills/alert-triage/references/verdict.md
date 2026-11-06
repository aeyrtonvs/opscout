# The verdict

The JSON object passed to `check_verdict`. Unknown keys are refused.

```json
{
  "classification": "real",
  "summary": "Sustained 5XX errors after the 09:12 deployment of example-api.",
  "cause": {
    "text": "The deployment at 2026-11-06T09:12:00+00:00 started the errors.",
    "cites": [{"evidence": "ev-0a1b2c3d4e", "quote": "UpdateService"}]
  },
  "threshold": {
    "assessment": "keep",
    "proposal": null,
    "reason": "The threshold was crossed for 40 minutes, not a spike.",
    "cites": [{"evidence": "ev-5f6a7b8c9d", "quote": "52.0"}]
  },
  "claims": [
    {
      "text": "5XX count rose above 50 from 09:35 and stayed above it.",
      "cites": [{"evidence": "ev-5f6a7b8c9d", "quote": "50.5"}]
    }
  ],
  "assumptions": ["The alert carried no time; the invocation time was used."],
  "timezone": "UTC",
  "alert_timezone": null,
  "alert_time_source": "invocation",
  "environment": "example-prod",
  "identity": "reference identity",
  "missing": [],
  "skeptic": {"ran": false, "disagreed": false, "note": null}
}
```

| Field | Rule |
|---|---|
| `classification` | `real`, `false-positive` or `inconclusive` |
| `summary` | one sentence, at most 300 characters |
| `cause` | null, or `text` (at most 500 characters) and 1 to 10 `cites` |
| `threshold.assessment` | `keep`, `tune` or `not-assessable`; `proposal` is required for `tune` and null otherwise |
| `threshold.reason` | at most 500 characters |
| `threshold.cites` | 0 to 10; at least one checked citation for `keep` and `tune` |
| `claims` | 0 to 20, each with `text` and 1 to 10 `cites` |
| `assumptions` | 0 to 20 short sentences |
| `timezone`, `alert_timezone` | IANA names such as `UTC` or `Europe/Lisbon`; the second may be null |
| `alert_time_source` | `alert`, `user` or `invocation`, from `begin_triage` |
| `environment`, `identity` | as the AWS results state them, or null when none was read |
| `missing` | the kinds not read: `metrics`, `logs`, `changes`, `configuration`, `observability` |

A citation is exactly one of:

- `{"evidence": "ev-…", "quote": "…"}`: the id of an opscout tool result in this run, and
  text copied from one value in it (a number, a name, a time, part of a log line). The
  harness checks it.
- `{"observability": "<tool name>", "quote": "…"}`: something the observability server
  returned. It cannot be checked, so it never supports a classification, a cause or a
  threshold assessment alone.

## What fails the check

- an evidence id that this run did not produce;
- a quote that is not in one value of that result (field names do not count; a quote of
  one or two characters must be a whole value);
- `real` or `false-positive` with no checked citation among the claims;
- a cause, or a `keep` or `tune` assessment, with no checked citation of its own;
- an `environment` or `identity` that differs from the cited results;
- any text holding a secret-shaped value (a key, a token, a connection string);
- an unknown timezone.

`inconclusive` needs no citation.
