# Contract: the opscout MCP tools (spec 011)

- **Server**: `opscout`, started as `opscout mcp [--mock DIR]` over stdio. No other
  transport.
- **Results**: every tool returns structured content, which is the Envelope
  (data-model.md), or a tool error whose structured content is a ToolError.
- **Windows**: they take `since` and `until`, ISO 8601 timestamps with an offset, or
  `last` (`15m`, `3h`, `2d`); `until` defaults to now.
- **Environments**: tools that read AWS take `environment` (a configured name or alias)
  and an optional `region`, which must be one of the environment's regions and defaults to
  the first.

| Tool | Input | `data` | Declared actions |
|---|---|---|---|
| `list_environments` | — | `[{name, regions, aliases, identity}]` | none |
| `parse_alert` | `text` (≤ 20,000 chars) | ParsedAlert or `{"matched": false}` | none |
| `resolve_environment` | `fields` (a map from AlertField to text) and/or `text` | Resolution | none |
| `read_alarm` | `environment`, `name`, window, `region?` | the alarm (`state`, `reason`, `threshold`, `comparison`, `metric`, `dimensions`, `period`, `statistic`), `history` (state changes in the window), `datapoints` | `cloudwatch:DescribeAlarms`, `cloudwatch:DescribeAlarmHistory`, `cloudwatch:GetMetricData` |
| `read_metric` | `environment`, `namespace`, `metric`, `dimensions`, `statistic`, `period` (s), window, `region?` | `datapoints` `[{time, value}]`, `unit` | `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics` |
| `query_logs` | `environment`, `log_groups` (1–10), `query` (Logs Insights, ≤ 10,000 chars), window, `limit?`, `region?` | `rows`, `status` (`complete` \| `partial`), `statistics` | `logs:StartQuery`, `logs:GetQueryResults`, `logs:StopQuery`, `logs:DescribeLogGroups` |
| `recent_changes` | `environment`, window, `resource?` (ResourceRef), `region?` | `changes` `[{time, source, actor, action, target, status, error}]`, newest first, and `more` per source; never an event's request or response contents nor a stack event's resource properties (research R12) | `cloudtrail:LookupEvents`, `cloudformation:DescribeStacks`, `cloudformation:DescribeStackEvents`, `ecs:ListServiceDeployments`, `autoscaling:DescribeScalingActivities`, `rds:DescribeEvents` |
| `find_resources` | `environment`, `name?`, `tag?` (`key`, `value?`), `type?`, `region?` (at least one of `name` or `tag`) | `resources` `[{type, name, arn, tags}]` | `tag:GetResources` |
| `describe_resource` | `environment`, ResourceRef, `region?` | `type`, `configuration` (the type's reviewed fields), and `stack` for Lambda | `ecs:DescribeServices`, `ecs:ListClusters`, `rds:DescribeDBInstances`, `rds:DescribeDBClusters`, `ec2:DescribeInstances`, `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetGroups`, `elasticloadbalancing:DescribeTargetHealth`, `elasticloadbalancing:DescribeListeners`, `autoscaling:DescribeAutoScalingGroups`, `cloudwatch:DescribeAlarms`, `cloudformation:DescribeStackResources`, `cloudformation:ListStackResources`, `cloudformation:DescribeStacks` |

## `describe_resource`, per type

| Type | Read | Returned |
|---|---|---|
| `ecs-service` | `DescribeServices` (cluster from the name or ARN, or each cluster from `ListClusters` tried) | status, desired, running and pending counts, the task definition's ARN only (never its contents), launch type, deployments, load balancers, network configuration, the last 10 events |
| `rds-instance`, `rds-cluster` | `DescribeDBInstances`, `DescribeDBClusters` | engine and version, class, status, multi-AZ, storage, endpoints, parameter group names, backup window and retention, maintenance window, pending changes. A master password is never returned by these reads. |
| `ec2-instance` | `DescribeInstances` | type, state, AMI, subnet, VPC, security groups, IAM profile ARN, launch time, tags. User data is not part of this read. |
| `load-balancer`, `target-group` | `DescribeLoadBalancers`, `DescribeListeners`, `DescribeTargetGroups`, `DescribeTargetHealth` | scheme, state, listeners, the health check, target health |
| `autoscaling-group` | `DescribeAutoScalingGroups` | min, max and desired, instances and their health, launch template (ID and version), target groups |
| `alarm` | `DescribeAlarms` | as in `read_alarm`, without datapoints |
| `lambda-function` | `DescribeStackResources(PhysicalResourceId=…)`, then `ListStackResources` and `DescribeStacks` | the owning stack: its status and last update, its outputs, and the resource rows for the function. Never the stack's parameters or template. A function no stack owns returns `not-found` with the reason "described only through its CloudFormation stack". |

Any other type returns `not-supported`, with the list above.

## Errors

| Reason | When | `fix` |
|---|---|---|
| `not-configured` | the tool needs `aws` or `alerts` and the section is absent | the configuration reference |
| `invalid-config` | the configuration fails validation | `opscout config validate` |
| `unknown-environment` | the name or alias is not configured | — (the message lists the configured names) |
| `profile-missing`, `login-expired`, `no-credentials`, `unreachable`, `throttled` | research R8 | as R8 |
| `denied` | AWS refused the call | — (the message names the action) |
| `undeclared-action` | the tool tried an action it did not declare | — (this is a defect) |
| `not-found`, `not-supported`, `invalid-input` | as named | — |
| `fixture-missing` | mock mode, no fixture matched | — (the message names the file and the parameters) |
