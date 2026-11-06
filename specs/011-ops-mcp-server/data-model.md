# Data model: Read-only tools for the investigation agents (spec 011)

All models are immutable and validated. Times are timezone-aware.

## Configuration (private, schema version 1, additive)

### AlertFormat (`alerts.formats[]`)

| Field | Type | Rules |
|---|---|---|
| `name` | string | 1–64 chars, `[a-z0-9-]`, unique |
| `recognize` | regex | compiles; ≤ 500 chars |
| `fields` | map: AlertField → regex | ≥ 1 entry; each compiles, ≤ 500 chars, exactly one capture group |

`AlertField` is one of `severity`, `title`, `project`, `environment`, `resource`, `account`,
`region`, `metric`, `threshold`, `value` and `time`. Matching is multi-line, and the order
of `formats` is the order of precedence.

### Environment (`aws.environments[]`)

| Field | Type | Rules |
|---|---|---|
| `name` | string | 1–64 chars, `[A-Za-z0-9._-]`, unique |
| `account_id` | string | exactly 12 digits, unique |
| `profile` | string | 1–128 chars, an AWS profile name |
| `regions` | list of strings | 1–10, each `^[a-z]{2}(-[a-z]+)+-\d$`; the first is the default |
| `aliases` | list of strings | optional, ≤ 20, unique across environments (case-insensitive), never equal to another environment's name |
| `identity` | `reference` \| `own` | default `own` |

### Tools (`tools`)

| Field | Type | Rules |
|---|---|---|
| `timezone` | IANA name | default: `personal_context.timezone`, else `UTC` |
| `redact.account_ids` / `.ips` / `.emails` | bool | default false |
| `caps.<name>` | int | 1 ≤ value ≤ the ceiling in research R7 |

## Core

- **ToolSpec**: the `name`, the `description`, the `actions` (frozenset of IAM action
  names; empty for tools that call no cloud) and `needs_aws` (true exactly when `actions`
  is not empty).
- **Registry**: the tuple of ToolSpecs; names are unique.
- **Window**: `start` and `end`, both aware. A window is valid when start < end ≤ now + 5
  minutes. If its length passes the tool's maximum, the start moves later and `capped`
  records it.
- **Caps**: the effective value of each cap (R7), computed from the ceilings and the
  configuration.
- **Envelope**, which every tool returns:
  - `environment`: the name, or null for tools without an environment;
  - `identity`: `"reference identity"` or `"own identity, not verified"`, or null;
  - `timezone`;
  - `window`: optional;
  - `capped`: a list of `{cap, limit, dropped}`;
  - `redacted`: a map from kind to count;
  - `partial`: true when the deadline stopped the tool before it finished (research R7);
  - `data`: the tool's payload.
- **ToolError**: the `reason` (an enum: `not-configured`, `invalid-config`,
  `unknown-environment`, `profile-missing`, `login-expired`, `no-credentials`,
  `unreachable`, `throttled`, `denied`, `undeclared-action`, `not-found`, `not-supported`,
  `invalid-input`, `fixture-missing`, `internal-error` for any other failure, whose
  message names only the exception's type), the `message`, and an optional `fix`, the command
  to run.
- **ParsedAlert**: `format` (the name), `fields` (a map from field to `{value, source}`)
  and `also_matched` (the names of later formats that matched too). Or `NoMatch`.
- **Resolution**: an `environment`, or `out_of_scope`, together with `matched_by` (the
  field and its value).
- **ResourceRef**: the `type` (one of `ecs-service`, `rds-instance`, `rds-cluster`,
  `ec2-instance`, `load-balancer`, `target-group`, `autoscaling-group`, `alarm` or
  `lambda-function`), the `name` or `arn`, and the `region`.

## Port

- **AwsGateway** (Protocol): `call(environment: Environment, region: str, action: str,
  params: Mapping, allowed: frozenset[str]) -> Mapping`. It raises GatewayError (with a
  ToolError reason) and never returns anything for an action outside `allowed`. There are
  two adapters: live (boto3) and fixtures.
- **CallLog** (Protocol): `append(entry)`, where the entry holds the time, the tool, the
  environment, the outcome, the duration in milliseconds and the redaction counts.

## Changes to spec 010's records

- In `capabilities.json`, `changes` gains `cloudformation:DescribeStackEvents`. A new
  capability, `inventory`, is added: purpose "Find resources by tag and the stack that
  owns them", agents alert-triage and ask, identity readonly, not optional, grant actions,
  with `tag:GetResources` and `cloudformation:DescribeStackResources`.
- The reference tree gains `aws/readonly/capabilities/inventory.json`, and
  `aws/readonly/capabilities/changes.json` gains the action.
