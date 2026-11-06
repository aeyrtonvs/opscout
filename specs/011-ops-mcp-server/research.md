# Research: Read-only tools for the investigation agents (spec 011)

Facts checked on 2026-11-06 unless a date says otherwise.

## R1. The MCP server library

- **Decision**: the official Python SDK, `mcp>=2.3,<3` (MIT, 2.3.0 released 2026-10-02),
  through its high-level `mcp.server.mcpserver.MCPServer`: `add_tool(...)` and
  `run("stdio")`. Contract tests use its `mcp.Client`, which connects to an `MCPServer`
  instance in-process; one end-to-end test launches `opscout mcp` as a subprocess with
  `StdioServerParameters`.
- **Locked**: `mcp` 2.3.0 (T002, 2026-11-06).
- **Rationale**: the protocol now has two eras. Revisions 2024-11-05 to 2025-11-25 use the
  `initialize` handshake; 2026-07-28 uses a stateless per-request envelope with
  `server/discover` (`mcp_types.version`). Negotiating both, and following the next
  revision, is the SDK's job. Claude Code is the client, and ADR-0009 names MCP as the
  standard, so a conforming SDK is worth more than a smaller hand-written loop.
- **Cost**: the SDK depends on a web stack (`starlette`, `uvicorn`, `sse-starlette`,
  `httpx2`, `pyjwt[crypto]`, `opentelemetry-api`) that a stdio server never imports. All are
  MIT, BSD or Apache-2.0; CI's dependency review covers them. `pydantic>=2.12` is already
  satisfied.
- **Alternatives**: `mcp-types` (wire types only, depends on pydantic) plus a hand-written
  stdio JSON-RPC loop: rejected, because it means owning the version negotiation of both
  eras. `mcp<2`: rejected, the 1.x line is in maintenance and its `FastMCP` name is removed
  in 2.x.

## R2. The AWS SDK and how it is installed

- **Decision**: `boto3>=1.43,<2` (Apache-2.0) as the `aws` optional extra, as ADR-0011 says
  (`opscout[aws]`). The plugin's launcher always asks for the extra: `uv run --extra aws`
  in a clone, `uvx --from "opscout[aws]==<version>"` for a release. boto3 is imported only
  when a cloud tool runs, so the server lists its tools without loading it (SC-002).
- **Locked**: `boto3` and `botocore` 1.43.125 (T002, 2026-11-06). The `dev` group holds
  `opscout[aws]`, so tests and types always have them.
- **Rationale**: botocore reads the AWS CLI's profiles and its single sign-on token cache,
  including `sso-session` sections, so opscout stores no credential (Assumptions).
  Threads: a boto3 `Session` is not thread-safe and the SDK may run tools in parallel, so
  each environment's session and clients are created once under a lock and cached; boto3
  clients are thread-safe. Typing:
  boto3 ships no types; a mypy override marks `boto3` and `botocore` as untyped, and only
  the adapter imports them, behind typed models.
- **Alternatives**: shelling out to the `aws` CLI: rejected, it is a shell, its operations
  cannot be refused before they run, and its output needs parsing. `types-boto3` stubs:
  not needed for the eleven operations used; reconsider if the adapter grows.

## R3. The surface check (FR-005 to FR-007)

- **Decision**: each tool declares its AWS actions in the registry. A test runs
  `prove_surface(registry, records)`, which reuses spec 010's catalog and evaluator. Every
  declared action must be in the catalog, must not be a write, and must be proved allowed
  by the reference read-only identity (`proves_allowed(readonly_identity(...), action,
  "*")`). That identity's guardrail denies secret values, credentials, reads that return
  plaintext secrets, application data and sessions, so the one check covers all of them.
  A planted tool declaring `secretsmanager:GetSecretValue`, `lambda:GetFunctionConfiguration`
  or `ec2:CreateTags` must fail with the tool and action named.
- **Run-time guard (FR-007)**: the live gateway registers a botocore `before-call` handler.
  It maps the call's service and operation to an IAM action through a fixed table, and
  refuses any action the calling tool did not declare before the request is signed. For
  the services used, the operation name is the IAM action name; the table maps the
  service: `cloudwatch`, `logs`, `cloudtrail`, `cloudformation`, `ecs`, `autoscaling`,
  `rds`, `ec2`, `elbv2` → `elasticloadbalancing`, and `resourcegroupstaggingapi` → `tag`. A
  test checks every table entry against the catalog.

## R4. Operations the tools need, against the reference identity

Checked with spec 010's evaluator:

- **Allowed now**:
  - CloudWatch: `DescribeAlarms`, `DescribeAlarmHistory`, `GetMetricData`, `ListMetrics`.
  - CloudWatch Logs: `StartQuery`, `GetQueryResults`, `StopQuery`, `DescribeLogGroups`.
  - CloudTrail: `LookupEvents`.
  - CloudFormation: `DescribeStacks`, `ListStackResources`.
  - ECS: `ListServiceDeployments`, `DescribeServiceDeployments`, `DescribeServices`,
    `ListServices`, `ListClusters`.
  - Auto Scaling: `DescribeScalingActivities`, `DescribeAutoScalingGroups`.
  - RDS: `DescribeEvents`, `DescribeDBInstances`, `DescribeDBClusters`.
  - EC2: `DescribeInstances`.
  - Elastic Load Balancing: `DescribeLoadBalancers`, `DescribeTargetGroups`,
    `DescribeTargetHealth`, `DescribeListeners`.
- **Denied, and never used**: `ecs:DescribeTaskDefinition`, `ec2:DescribeInstanceAttribute`,
  `lambda:GetFunctionConfiguration` and `lambda:ListFunctions`, all by the guardrail's
  plaintext-secrets group. This is why ECS services are described without their task
  definition, and Lambda only through its stack (clarification 2).
- **Missing, and needed**:
  - `cloudformation:DescribeStackEvents`, for stack events in recent changes;
  - `cloudformation:DescribeStackResources`, to find the stack that owns a Lambda function
    by its physical ID;
  - `tag:GetResources`, to find resources by tag or `Name`.

  `ViewOnlyAccess` grants none of the three, and the `ReadOnlyAccess` cap allows all three.
  The spec's assumption applies: spec 010's capabilities change first.
  - `changes` gains `cloudformation:DescribeStackEvents`.
  - A new `inventory` capability (alert-triage and ask) holds `tag:GetResources` and
    `cloudformation:DescribeStackResources`. `opscout identity check` must still pass,
    and its counts change: reads go from 42 to 45, and policies from 8 to 9.

## R5. Fixtures and mock mode (FR-025 to FR-027)

- **Decision**: a second gateway adapter answers from a directory:
  `<dir>/<environment>/<service-prefix>/<Action>.json`, where `<dir>` is the directory
  passed to `--mock`. Each file holds a list of
  `{"match": {<request parameter subset>}, "response": {...}}` or
  `{"match": {...}, "error": {"reason": ..., "fix": ...}}`, where `reason` is a tool error
  reason (data-model.md). The first match wins. Timestamps written as ISO 8601 with an
  offset become datetimes, as botocore returns them. With no
  file or no match, the error names the file and the parameters it looked for, and nothing
  falls back to a live call. The same `before-call` declaration check runs, so a tool
  cannot read a fixture for an action it did not declare.
- **Selection**: `opscout mcp --mock DIR`. The plugin's `.mcp.json` never passes it. Evals
  start their own server with the flag, through `--strict-mcp-config` (spec 007's runner).
- **Where**: `evals/mcp/aws/` at the repository root (the `--mock` directory), beside
  `evals/mcp/alerts/` (the alert corpus) and `evals/standup/`, with fake values only. The
  next spec's evals reuse both.
- **Alternatives**: botocore's `Stubber`, which is kept for the live adapter's unit tests,
  but it is too strict about call order for agent-driven runs. `moto`: a new dependency
  that emulates far more than is needed.

## R6. Redaction (FR-009, FR-010)

- **Decision**: extend `services/redact.py` (spec 009) with a `keep` set of kinds:
  `account-id`, `ip` and `email`. The tools pass the kinds the configuration does not
  redact; by default they keep all three (clarification 1). Phone numbers stay always
  redacted: an investigation does not need them, and they are personal data.
- **Structure**: redaction walks the tool's result rather than its serialized text, so
  JSON stays valid.
  - Every string leaf goes through `redact`.
  - A key whose name matches the secret names (`password`, `secret`, `token`, `api_key`
    and the rest) has its value replaced by `[secret]`, whatever its type.
  - A name-and-value pair is treated the same way: in a dict with a name field (`Key`,
    `Name`, `ParameterKey`, `OutputKey`) whose value matches the secret names, the value
    field (`Value`, `ParameterValue`, `OutputValue`) becomes `[secret]`. AWS returns tags,
    stack outputs and parameters in this shape, where the secret-sounding name is a value,
    not a key.
  - Counts are summed into the result's `redacted` field.
- **Alternatives**: redacting the serialized JSON: rejected, a connection-string match can
  swallow a closing quote.

## R7. Caps (FR-011)

Hard ceilings live in code. The configuration may lower them, never raise them.

| Cap | Default | Ceiling |
|---|---|---|
| Characters in one result | 40,000 | 40,000 |
| Window, alarms and metrics | 3 h | 14 days |
| Window, log query | 1 h | 24 h |
| Window, recent changes | 24 h | 7 days |
| Log rows | 100 | 1,000 |
| Log query wait | 30 s | 50 s |
| Change items | 50 | 200 |
| Stacks examined for events | 10 | 25 |
| Found resources | 25 | 100 |
| Metric data points | 500 | 1,440 |

- **The 40,000-character ceiling**: Claude Code warns when an MCP result passes 10,000
  tokens, and that is about 40,000 characters.
- **Trimming**: when a result would exceed its size cap, whole items are dropped from the
  end, and `capped` says how many.
- **Timeouts**: each AWS call gets a 5-second connect timeout and a 20-second read timeout.
- **Deadline**: every tool call has a 45-second deadline, checked before each AWS call.
  Past it, the tool makes no further call and returns what it has, marked `partial`.
  - The log query's wait is measured by the clock, polls included, and ends 12 seconds
    before the deadline, which leaves time to stop the query.
  - Each AWS call gets a budget: the time left plus 10 seconds. Every attempt, connect
    plus read, fits in it. There is one retry only when two full attempts fit; otherwise
    the read timeout is the budget minus the connect timeout, at most 20 seconds.
  - A handler stopped by the deadline keeps its environment, and returns what it found
    where it can (review M4, M5).

  Every tool therefore returns within about 55 seconds, under SC-003's 60.

## R8. Errors (FR-004, US5)

botocore's errors map to fixed reasons:

| botocore error | Reason | Fix command |
|---|---|---|
| `ProfileNotFound` | the profile is not in the AWS config | `aws configure sso` |
| SSO token missing or expired (`TokenRetrievalError`, `UnauthorizedSSOTokenError`, `SSOTokenLoadError`) | the login expired | `aws sso login --profile <p>` (or `--sso-session`), as spec 005 words it |
| `NoCredentialsError` | no credentials | none |
| `EndpointConnectionError`, `ConnectTimeoutError`, `ReadTimeoutError` | unreachable | none |
| `ClientError` with a throttling code | throttled | none |
| `ClientError` with `AccessDenied*` or `UnauthorizedOperation` | the identity does not allow it | none; the result names the action |

Throttling uses botocore's `standard` retry mode with `total_max_attempts=2`, one retry
after the delay botocore computes, when the call's budget fits two attempts; with less time
left, a call gets one attempt (R7). (botocore reads `max_attempts` as retries, so
`max_attempts=2` would be three calls; found in T019.) No error stops the server.

## R9. Configuration (FR-014 to FR-016)

Three new optional sections in schema version 1, each an additive change (spec 002, ADR-0014):

- `alerts.formats[]`, one entry per format:
  - `name`;
  - `recognize`, a regular expression;
  - `fields`, mapping each field (`severity`, `title`, `project`, `environment`, `resource`,
    `account`, `region`, `metric`, `threshold`, `value`, `time`) to a regular expression
    with exactly one capture group.

  Every expression is compiled at validation, and is at most 500 characters. The alert
  text is cut at 20,000 characters before matching, which bounds backtracking.
- `aws.environments[]`, one entry per environment: `name`, `account_id` (12 digits),
  `profile`, `regions` (one or more; the first is the default), `aliases` (optional), and
  `identity` (`reference` or `own`, default `own`). Names, aliases and account IDs are
  unique across environments.
- `tools`:
  - `timezone`, which defaults to `personal_context.timezone`, then UTC;
  - `redact` (`account_ids`, `ips`, `emails`, each default false);
  - `caps`, which may lower the ceilings in R7.

## R10. The plugin starts the server (FR-001, FR-029)

- **Decision**: `plugins/opscout/.mcp.json` holds one server, `opscout`, that runs
  `${CLAUDE_PLUGIN_ROOT}/bin/opscout` with `["mcp"]`. It passes the configuration directory
  as `OPSCOUT_CONFIG=${user_config.config_dir}`. The CLI already ignores an unsubstituted
  `${user_config.…}` value (spec 003, FR-009). Whether Claude Code substitutes
  `${user_config.…}` in a plugin MCP server's `env` is not verified yet; quickstart step 5
  checks it, and this note records the result.
- **Result (live run, 2026-11-06)**: Claude Code substitutes the option when it is set, and
  refuses to start the server when it is not (`Plugin option "config_dir" isn't set`).
  MCP servers get no `CLAUDE_PLUGIN_OPTION_*` variables, unlike hooks. So `config_dir` has
  an empty `default` and is not required: an empty `OPSCOUT_CONFIG` means the usual
  resolution order, and the server starts with no option set.
- **Launcher**: adds the `aws` extra (R2). Unlike the session hook, it must never print a
  JSON hook message for `mcp`; on a missing `uv` it writes to stderr and exits 127, as for
  any command, and with no release to run it exits 1 (both checked in T023).
- **Checks**: a test reads `.mcp.json` and runs the same command with `StdioServerParameters`
  against the clone; `claude plugin eval` and `uv run just plugin` keep validating the
  plugin. The live check lists the tools in a session (`/mcp`).

## R11. Local record of tool calls (Constitution IX)

Each call appends one JSON line to `opscout/mcp-calls.jsonl` under the platform state
directory. The line holds:

- the time, the tool and the environment;
- the outcome (ok, capped or the error reason);
- the duration and the redaction counts.

It never holds arguments or output: a query or a resource name can carry private text. The
runner's record (spec 007) links to these lines by time.

## R12. Recent changes, bounded (FR-022)

One call returns, merged and sorted newest first, with each source capped and named:

- CloudTrail `LookupEvents` with `ReadOnly=false` over the window, optionally narrowed by
  `ResourceName`;
- the CloudFormation stack events of stacks updated in the window (`DescribeStacks`, then
  `DescribeStackEvents`), the most recently updated stacks first, up to the stacks cap;
- when a resource is given and its type has one:
  - ECS service deployments;
  - Auto Scaling activities;
  - RDS events.

CloudTrail's `LookupEvents` is limited to 2 requests per second per account. One page of
up to 50 events is read per window, and the result says when more exist.

What a change carries:

- **From a CloudTrail event**: the time, the user identity's ARN or name, the event name,
  the event source, the resource names and types, and the error code and message.
- **From a stack event**: the time, the stack, the logical and physical IDs, the type, the
  status and its reason.

`CloudTrailEvent`'s `requestParameters` and `responseElements` are never read into the
result: a task definition's registration, for one, logs its environment values. A stack
event's `ResourceProperties` is never read either: it is the resource's full properties,
passwords included.
