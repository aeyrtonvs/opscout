# Contract: configuration sections (spec 011)

All three sections are optional, and each is an additive change to schema version 1
(spec 002). The values here are fake.

```yaml
alerts:
  formats:
    - name: example-notifier
      recognize: '^(CRITICAL|WARNING): '
      fields:
        severity: '^(CRITICAL|WARNING): '
        title: '^(?:CRITICAL|WARNING): (.+)$'
        project: '^Project: (.+)$'
        environment: '^Environment: (.+)$'
        resource: '^Resource: (.+)$'
        account: '^Account: (\d{12})'
        region: '^Region: ([a-z0-9-]+)$'
        metric: '^Metric: (.+)$'
        threshold: '^Threshold: (.+)$'
    - name: example-monitor
      recognize: '^Triggered: \['
      fields:
        project: '^Triggered: \[([^\]]+)\]'
        environment: '^Triggered: \[[^\]]+\]\[([^\]]+)\]'
        title: '^Triggered: (?:\[[^\]]+\]){2} ?(.+)$'

aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1]
      aliases: [Production, prod]
      identity: reference
    # Each further environment has its own account ID, profile and regions.

tools:
  timezone: Europe/Madrid
  redact:
    ips: false
    emails: true
  caps:
    log_rows: 200
```

Validation errors use spec 002's form: `file:line:column: path: message`. Examples:

- `alerts.formats[0].fields.account: needs exactly one capture group`
- `aws.environments[1].aliases[0]: "prod" is already used by example-prod`
- `tools.caps.log_rows: at most 1000`
