# Read-only tools reference

opscout's tool server, `opscout mcp`, gives Claude Code typed tools for investigating
alerts (spec 011). The plugin starts it in every session over standard input and output, as
a local process with no network port, so skills and subagents call tools instead of shell
commands. Check it with `/mcp` in a session: `opscout` is connected, with nine tools.

**Every tool only reads.** Each one declares the AWS actions it may call. A test proves
that every declared action is in AWS's recorded catalog, is not a write, and is allowed by
opscout's reference read-only identity (spec 010). At run time, any call outside a tool's
declarations is refused before it is sent. So no tool writes anything or returns a
secret's value, whichever identity runs it (ADR-0023).

**Each integration is optional.** With no AWS configured, the server still starts, the
alert tools work, and every AWS tool answers `not-configured`.

## The tools

| Tool | What it returns |
|---|---|
| `list_environments` | The configured environments: names, regions, aliases and identity kind. |
| `parse_alert` | The first declared alert format that matches the text, and each of its fields with the text it came from. It never guesses a field. |
| `resolve_environment` | The environment an alert belongs to, by account ID, name or alias; or "out of scope", with what did not match. |
| `read_alarm` | A CloudWatch alarm's state, reason, threshold and state changes, and its metric over the window. |
| `read_metric` | A metric's data points, by namespace, name, dimensions, statistic and period. |
| `query_logs` | The rows and statistics of a Logs Insights query over one to ten log groups. The rows are capped by `log_rows` or the query's own `limit`, whichever is smaller; `@timestamp` and `@ingestionTime` are given in the configured timezone; other time columns, such as `bin()`'s, come as Logs Insights writes them, in UTC. A query still running at the wait limit is stopped and marked partial. |
| `recent_changes` | Who changed what, when, newest first: API activity that changed something, stack events, and deployments, scaling activities or database events for a given resource. Agent heartbeats (such as `UpdateInstanceInformation` and `PutInventory`) and `triage.background_actions` are dropped and counted in `background_dropped`, unless `include_background` is true (spec 012). |
| `find_resources` | Resources found by name, tag or type. Only tagged resources appear, because the tagging API lists only those. |
| `describe_resource` | One resource's reviewed configuration. |
| `begin_triage` | Opens an alert triage run: the parsed alert, its environment or why none, the windows, the settings and the ticket format. Writes the run's local record (spec 012). |
| `check_verdict` | Checks a triage verdict against the tool results of the same run: one retry, then the run ends as inconclusive. |
| `record_agreement` | Records whether the user agrees with a run's verdict. |
| `show_evidence` | Earlier results by evidence id, as the model saw them. |
| `search_iac` | Lines of the configured infrastructure-code clones that contain a literal, with file and line. |
| `read_iac` | Up to 200 numbered lines of one file in a configured clone. |

What the tools never read:

- the request or response of a CloudTrail event, which can hold the values a change set,
  such as a task definition's environment;
- a stack event's resource properties, or a stack's parameters or template;
- an ECS task definition's contents (a service gives its task definition's ARN only);
- an instance's user data;
- a Lambda function's own configuration. A function is described only through the
  CloudFormation stack that owns it: the stack's status, outputs, and the function's rows.

`describe_resource` takes one of these types:

- `ecs-service`, as `cluster/service`, an ARN, or a name searched across clusters
- `rds-instance`
- `rds-cluster`
- `ec2-instance`, by ID or `Name` tag
- `load-balancer`
- `target-group`
- `autoscaling-group`
- `alarm`
- `lambda-function`

Any other type returns `not-supported`.

## Every result

Every tool returns the same envelope:

| Field | Meaning |
|---|---|
| `environment` | The environment read, or null. |
| `identity` | `reference identity` when the configuration declares that the environment uses spec 010's identity; `own identity, not verified` otherwise. opscout never checks it and never blocks on it. |
| `timezone` | The IANA timezone that every time in the result is written in, each with its offset. |
| `window` | The window read, if any. |
| `capped` | What each cap removed: `{cap, limit, dropped}`. For a window, `dropped` counts minutes. |
| `redacted` | How many values of each kind were redacted. |
| `partial` | True when the deadline stopped the tool before it finished. |
| `data` | The tool's data, or null on error. |
| `error` | `{reason, message, fix}` when the call failed, or null. |
| `evidence` | The result's evidence id, which a triage verdict cites; null for the tools that check or show evidence, and when the evidence store cannot be written (spec 012). |

## Redaction

Before a result reaches the model, every string in it is redacted:

- **Always:** private keys, connection strings, credentials and access keys, bearer
  tokens, values assigned to secret-sounding names (in `name=value`, `"name": "value"` and
  `--name value` forms), secret-shaped values, and phone numbers. Error messages are
  redacted too.
- **Secret-named values:** a key named like a secret (`password`, `token`, `api_key` and
  the like) has its value replaced by `[secret]`. So does a name-and-value pair whose name
  is secret-sounding, as AWS returns tags, stack outputs and parameters.
- **Kept by default:** account IDs, IP addresses and e-mail addresses, because an
  investigation needs them as evidence. Turn on their redaction in `tools.redact`.
- **Identifiers:** an ARN or an ECS task ID says where something is, so two narrow
  exceptions keep them whole: a 32-character hexadecimal ID inside an ARN or in an ECS
  event's `(task <id>)` is not taken for a secret, and an ARN's service and a Secrets
  Manager ARN's `secret:` are not taken for a secret's name. Every other rule still
  applies to them.

## Caps and the deadline

Each cap has a default, used when a call asks for nothing else, and a ceiling. The
configuration may lower a ceiling in `tools.caps`, never raise it.

| Cap | Default | Ceiling |
|---|---|---|
| `result_chars` | 40,000 | 40,000 |
| `metric_window_hours` | 3 | 336 |
| `log_window_hours` | 1 | 24 |
| `change_window_hours` | 24 | 168 |
| `log_rows` | 100 | 1,000 |
| `log_wait_seconds` | 30 | 50 |
| `change_items` | 50 | 200 |
| `stacks` | 10 | 25 |
| `resources` | 25 | 100 |
| `datapoints` | 500 | 1,440 |

How the caps apply:

- **Long strings:** a string longer than 4,000 characters is cut (`string_chars`).
- **Oversized results:** whole items are dropped from the end of the result until it fits
  `result_chars`.
- **Long alerts:** alert text beyond 20,000 characters is cut (`alert_chars`).
- **Data points:** a series keeps its newest points.
- **The deadline:** every call has a 45-second deadline. Past it, the tool makes no further
  AWS call and returns what it has, marked `partial`. Every tool returns within 60 seconds.

## Configuration

Three optional sections of the private configuration
([configuration.md](configuration.md)): `alerts`, `aws` and `tools`.

```yaml
alerts:
  formats:
    - name: example-notifier
      recognize: '^(CRITICAL|WARNING): '
      fields:
        severity: '^(CRITICAL|WARNING): '
        account: '^Account: (\d{12})'
aws:
  environments:
    - name: example-prod
      account_id: "123456789012"
      profile: example-prod
      regions: [us-east-1]
      aliases: [Production]
      identity: reference
tools:
  timezone: Europe/Lisbon
  redact:
    emails: true
  caps:
    log_rows: 200
```

AWS is reached through the named profiles in your AWS config; single sign-on logins work as
they do for the AWS CLI. opscout stores no credential.

## Errors

| Reason | When | Fix |
|---|---|---|
| `not-configured` | The tool needs `aws` or `alerts`, and that section is absent. | See Configuration above. |
| `invalid-config` | The configuration fails validation. | `opscout config validate` |
| `unknown-environment` | The name or alias is not configured. The message lists the configured names. | — |
| `profile-missing` | The environment's profile is not in your AWS config. | `aws configure sso` |
| `login-expired` | The single sign-on login expired. | `aws sso login --profile <profile>` |
| `no-credentials` | No credentials were found for the profile. | — |
| `unreachable` | AWS could not be reached, or failed. | — |
| `throttled` | AWS throttled the call; botocore retried once if time allowed. | — |
| `denied` | The identity does not allow the call. The message names the action. | — |
| `undeclared-action` | A tool tried an action it did not declare. This is a defect in opscout. | — |
| `not-found` | No such alarm, metric, log group or resource. | — |
| `not-supported` | A resource type outside the list. | — |
| `invalid-input` | A bad window, statistic, period, query or argument. | — |
| `fixture-missing` | Mock mode found no fixture for the call. The message names the file and the parameters. | — |
| `internal-error` | Anything else. The message names only the error's type; the server keeps running. | — |

## Mock mode

`opscout mcp --mock DIR` answers every AWS call from fixtures and never reaches AWS. Evals
and development use it; the plugin never passes it.

- **Layout:** each action of each environment has a file,
  `DIR/<environment>/<prefix>/<Action>.json`. The file holds entries
  `{"match": {...}, "response": {...}}` or `{"match": {...}, "error": {"reason": ...,
  "fix": ...}}`.
- **Matching:** the first entry whose `match` is a subset of the call's parameters answers.
  With none, the call fails with `fixture-missing`.
- **Shipped fixtures:** `evals/mcp/aws/` has fixtures for every declared action, with
  `evals/mcp/config.yaml`.

## The call log

Each call adds one JSON line to `mcp-calls.jsonl` in opscout's state directory. The line
holds the time, the tool, the environment, the outcome, the duration and the redaction
counts. It never holds a call's arguments or output.
