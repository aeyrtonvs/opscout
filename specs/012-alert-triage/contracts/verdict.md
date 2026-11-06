# Contract: the verdict (spec 012, FR-017 and FR-018)

The verdict is the JSON object the skill passes to `check_verdict`. Unknown keys are refused.

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

| Field | Type | Rule |
|---|---|---|
| `classification` | `real`, `false-positive`, `inconclusive` | FR-017's meanings |
| `summary` | string, 1 to 300 characters | one sentence |
| `cause` | object or null | `text` (1 to 500 characters) and `cites` (1 to 10) |
| `threshold.assessment` | `keep`, `tune`, `not-assessable` | `proposal` is required for `tune` and null otherwise |
| `threshold.reason` | string, 1 to 500 characters | |
| `threshold.cites` | 0 to 10 citations | at least one checked citation for `keep` and `tune` |
| `claims` | 0 to 20 | each `text` (1 to 500 characters) with 1 to 10 `cites` |
| `assumptions` | 0 to 20 strings | |
| `timezone`, `alert_timezone` | IANA name; the second may be null | |
| `alert_time_source` | `alert`, `user`, `invocation` | |
| `environment`, `identity` | string or null | must equal those of the AWS evidence cited |
| `missing` | subset of `metrics`, `logs`, `changes`, `configuration`, `observability` | |
| `skeptic` | `ran`, `disagreed` (booleans), `note` (string or null) | |

A citation is exactly one of:

- `{"evidence": "ev-…", "quote": "…"}`: checked against the stored result;
- `{"observability": "<tool name>", "quote": "…"}`: not checked, and counted as such.

`quote` is 1 to 300 characters.

## The check (research R5)

| Rule | Failure reason |
|---|---|
| The verdict validates against the schema above | `invalid: <pydantic message>` |
| Each evidence ID is in the store and was stored at or after the run's start | `unknown evidence` or `evidence from another run` |
| Each quote is found in one scalar of that result (whitespace collapsed; numbers by value; a quote under 3 characters must equal a whole scalar) | `quote not found` |
| `real` and `false-positive` have a checked citation among the claims | `no checked support for the classification` |
| A cause has a checked citation | `no checked support for the cause` |
| `keep` and `tune` have a checked citation | `no checked support for the threshold assessment` |
| `environment` and `identity` equal those of every cited AWS result that states them | `environment differs from the evidence` |
| No text field holds a secret-shaped value | `secret-shaped value in <path>` (the value is never repeated) |
| `timezone` and `alert_timezone` are IANA names | `unknown timezone` |

`inconclusive` needs no citation.
