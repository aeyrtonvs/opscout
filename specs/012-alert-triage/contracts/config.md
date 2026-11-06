# Contract: the `triage` configuration section (spec 012)

The section is optional, and it is an additive change to schema version 1 (spec 002).
Without it, triage runs with the defaults below: no infrastructure code, no observability
platform, no skeptic pass, 7 days of metric history. The values here are fake.

```yaml
triage:
  infrastructure:                 # local clones of infrastructure code, read only (FR-012)
    - name: example-infra         # how citations and read_iac name the clone
      path: /Users/example/src/example-infra
      environments: [example-prod]  # optional; absent means every environment
  observability: false            # true: a read-only server is registered as `observability` (FR-014)
  skeptic: false                  # the skeptic pass (FR-029, research R13)
  metric_history_days: 7          # 1 to 14 (FR-008, research R14)
  background_actions:             # more CloudTrail actions to drop as background (FR-009)
    - ExampleAgentHeartbeat
```

| Key | Type | Rule |
|---|---|---|
| `infrastructure` | list, at most 20 | each `name` matches `^[a-z0-9][a-z0-9-]{0,39}$` and is unique; `path` is absolute; `environments`, when given, names configured environments |
| `observability` | boolean | default false |
| `skeptic` | boolean | default false |
| `metric_history_days` | integer | 1 to 14, default 7 |
| `background_actions` | list of strings, at most 50 | each matches `^[A-Za-z][A-Za-z0-9]{0,127}$` |

Validation errors use spec 002's form and never repeat the refused value:

- `triage.infrastructure[0].path: must be an absolute path`
- `triage.infrastructure[1].name: is used by another clone`
- `triage.infrastructure[0].environments[0]: is not a configured environment`
- `triage.metric_history_days: at least 1 and at most 14`

A clone whose path does not exist is not a validation error; `search_iac` reports it as
missing.
