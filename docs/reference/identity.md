# Read-only identity reference

Phase 2's agents read untrusted text, such as alert bodies, log lines and chat threads,
while they reach real systems. The identity they use is the guarantee: even if an injected
instruction takes over the model, the identity can neither change anything nor read a
secret's value (spec 010, ADR-0010). opscout ships the reference identity as documents,
proves their properties offline with `opscout identity check`, and **never applies
anything**. Your infrastructure repository instantiates the documents.

## The two identities

| Identity | Attached | Permissions boundary | Used by |
|---|---|---|---|
| Read-only (one per environment) | AWS-managed `ViewOnlyAccess`, every file in `aws/readonly/capabilities/`, `aws/guardrail.json` | AWS-managed `ReadOnlyAccess` | every agent |
| Host (optional, one per environment) | `aws/hosts/capability.json`, `aws/guardrail.json` | `aws/hosts/boundary.json` | the host tool of alert triage |

- **The boundary is the cap.** `ReadOnlyAccess` allows no write, so a policy that someone
  attaches by mistake, even `Allow *`, cannot add a mutation.
- **The guardrail denies the rest.** It explicitly denies what `ReadOnlyAccess` still
  allows but must never be read: secret values, credential issuance, reads that return
  plaintext secrets, application data, sessions and shells, and the few actions AWS
  classifies as writes that `ReadOnlyAccess` lets through.
- **Host commands get their own identity** because `ssm:SendCommand` is a write. That
  identity can send only the seven catalog documents.

## Capabilities

Every permission belongs to a capability. Leave out an optional one by deleting its files.

| Capability | Identity | Optional | Agents | Grants | Purpose |
|---|---|---|---|---|---|
| configuration | readonly | no | alert-triage, cost-triage, ask | AWS-managed `ViewOnlyAccess` | View the configuration metadata of every service: what exists and how it is set, never secret values. |
| secret-metadata | readonly | no | alert-triage, ask | `secretsmanager:ListSecrets`, `secretsmanager:DescribeSecret`, `ssm:DescribeParameters` | Say whether a secret or parameter exists and where, never its value. |
| metrics | readonly | no | alert-triage | `cloudwatch:GetMetricData`, `cloudwatch:GetMetricStatistics`, `cloudwatch:GetMetricWidgetImage`, `cloudwatch:ListMetrics`, `cloudwatch:DescribeAlarms`, `cloudwatch:DescribeAlarmHistory`, `cloudwatch:DescribeAlarmsForMetric` | Read metrics and alarms around an alert. |
| logs | readonly | no | alert-triage | `logs:DescribeLogGroups`, `logs:DescribeLogStreams`, `logs:FilterLogEvents`, `logs:GetLogEvents`, `logs:StartQuery`, `logs:StopQuery`, `logs:GetQueryResults`, `logs:DescribeQueries` | Query and read log events around an alert. |
| changes | readonly | no | alert-triage, ask | `cloudtrail:LookupEvents`, `ecs:ListServiceDeployments`, `ecs:DescribeServiceDeployments`, `codedeploy:ListDeployments`, `codedeploy:GetDeployment`, `codedeploy:BatchGetDeployments`, `autoscaling:DescribeScalingActivities`, `rds:DescribeEvents`, `health:DescribeEvents` | Find recent changes: the audit trail, deployments and scaling events. |
| cost | readonly | no | cost-triage | `ce:GetCostAndUsage`, `ce:GetCostAndUsageWithResources`, `ce:GetCostForecast`, `ce:GetDimensionValues`, `ce:GetAnomalies`, `ce:GetAnomalyMonitors`, `ce:GetTags`, `budgets:ViewBudget` | Break down cost and usage, forecasts and anomalies. |
| cluster | readonly | yes | alert-triage, ask | `eks:DescribeCluster`, `eks:ListClusters` | Find EKS clusters and reach them with the view access policy. |
| hosts | hosts | yes | alert-triage | `ssm:SendCommand`, `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`, `ssm:ListCommands`, `ssm:DescribeInstanceInformation` | Run the catalog's fixed read-only commands on managed Linux hosts, and read their output. |

`opscout identity check` proves that every listed action is allowed, that nothing outside
this table is granted, and that every guardrail entry is denied even with `Allow *`
attached.

## The documents

`opscout identity export DIR` writes them:

- `aws/guardrail.json`
- `aws/readonly/capabilities/secret-metadata.json`
- `aws/readonly/capabilities/metrics.json`
- `aws/readonly/capabilities/logs.json`
- `aws/readonly/capabilities/changes.json`
- `aws/readonly/capabilities/cost.json`
- `aws/readonly/capabilities/cluster.json`
- `aws/hosts/capability.json`
- `aws/hosts/boundary.json`
- `ssm/opscout-ReadOnly-Uptime.yaml`
- `ssm/opscout-ReadOnly-Memory.yaml`
- `ssm/opscout-ReadOnly-Disk.yaml`
- `ssm/opscout-ReadOnly-TopProcesses.yaml`
- `ssm/opscout-ReadOnly-ServiceState.yaml`
- `ssm/opscout-ReadOnly-ServiceLog.yaml`
- `ssm/opscout-ReadOnly-ListeningPorts.yaml`
- `eks/access-policy.json`
- `kubernetes/view-binding.yaml`

**Placeholders**: the account `123456789012` (in the host ARNs, the guardrail's command
limit and the EKS principal), the cluster `example-prod`, the role `opscout-readonly` and
the group `opscout:readonly`. One tree is one account.

**Optional parts**: `aws/readonly/capabilities/cluster.json`; `aws/hosts/` together with
`ssm/`; `eks/`; `kubernetes/`.

**What the package owns**: the action catalog, the copies of the two managed policies,
the capability declarations and the guardrail's reviewed list stay in the package. A copy
is always proved against the installed opscout, so it cannot weaken them.

## Instantiating

1. Export, fill the placeholders, and delete what you do not use:

   ```sh
   opscout identity export opscout-identity
   opscout identity check opscout-identity
   ```

2. Attach the documents. The files stay as they are, and Terraform loads them with
   `file()`. As an IAM role (fake values):

   ```hcl
   resource "aws_iam_role" "opscout_readonly" {
     name                 = "opscout-readonly"
     assume_role_policy   = data.aws_iam_policy_document.trust.json
     permissions_boundary = "arn:aws:iam::aws:policy/ReadOnlyAccess"
   }

   resource "aws_iam_policy" "opscout_guardrail" {
     name   = "opscout-guardrail"
     policy = file("${path.module}/opscout-identity/aws/guardrail.json")
   }

   resource "aws_iam_policy" "opscout_capability" {
     for_each = fileset("${path.module}/opscout-identity/aws/readonly/capabilities", "*.json")
     name     = "opscout-${trimsuffix(each.value, ".json")}"
     policy   = file("${path.module}/opscout-identity/aws/readonly/capabilities/${each.value}")
   }

   resource "aws_iam_role_policy_attachment" "opscout_view_only" {
     role       = aws_iam_role.opscout_readonly.name
     policy_arn = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
   }
   ```

   Attach the guardrail and each capability the same way. The host identity is a second
   role: `aws/hosts/capability.json` and the guardrail attached, with
   `aws/hosts/boundary.json` as a customer-managed policy used as its
   `permissions_boundary`.

   As an IAM Identity Center permission set:
   - Attach `ViewOnlyAccess` with `aws_ssoadmin_managed_policy_attachment`.
   - Attach the guardrail and the capabilities as customer-managed policies with
     `aws_ssoadmin_customer_managed_policy_attachment`. A customer-managed policy with the
     same name must exist in each account.
   - Attach `ReadOnlyAccess` as the boundary with
     `aws_ssoadmin_permissions_boundary_attachment`.
   - Every document fits one customer-managed policy (6,144 characters). The guardrail and
     the capabilities together fit the permission set's single inline policy (10,240).

3. Register the host documents. Each document's name is its file name:

   ```hcl
   resource "aws_ssm_document" "opscout" {
     for_each        = fileset("${path.module}/opscout-identity/ssm", "*.yaml")
     name            = trimsuffix(each.value, ".yaml")
     document_type   = "Command"
     document_format = "YAML"
     content         = file("${path.module}/opscout-identity/ssm/${each.value}")
   }
   ```

4. For each cluster, create an access entry for the role, then associate the policy in
   `eks/access-policy.json` (`aws_eks_access_entry` and
   `aws_eks_access_policy_association`). For a cluster that maps identities through RBAC,
   apply `kubernetes/view-binding.yaml` and map the role to the group `opscout:readonly`.

## The pre-commit hook

In the infrastructure repository's `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/aeyrtonvs/opscout
  rev: <commit>
  hooks:
    - id: opscout-identity-check
      args: [opscout-identity]
      files: ^opscout-identity/
```

The directory holds only the identity's files; a `README.md` and dotfiles are ignored.
The command exits 0 when everything is proved, 1 with one line per finding, and 2 when a
file cannot be read.

## Live check

Run these once the identity exists in a sandbox account. None of them can change anything,
even if the identity were wrong. Record each outcome in spec 010's Actuals.

First, an administrator simulates the real attached policies and boundary. The simulation
changes nothing:

```sh
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::123456789012:role/opscout-readonly --action-names secretsmanager:GetSecretValue ssm:GetParameter kms:Decrypt sts:AssumeRole lambda:GetFunctionConfiguration s3:GetObject ssm:StartSession  # expect: every EvalDecision is explicitDeny or implicitDeny
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::123456789012:role/opscout-readonly --action-names ec2:RunInstances ec2:CreateTags iam:CreateUser s3:PutObject ssm:SendCommand rds:DeleteDBInstance  # expect: every EvalDecision is explicitDeny or implicitDeny
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::123456789012:role/opscout-readonly --action-names cloudwatch:GetMetricData logs:StartQuery cloudtrail:LookupEvents ce:GetCostAndUsage secretsmanager:DescribeSecret eks:DescribeCluster  # expect: every EvalDecision is allowed
```

Then, as the read-only identity, on resources that do not exist and with dry runs:

```sh
aws secretsmanager get-secret-value --secret-id opscout-probe-does-not-exist  # expect: AccessDeniedException, not ResourceNotFoundException
aws ssm get-parameter --name /opscout/probe-does-not-exist --with-decryption  # expect: AccessDeniedException, not ParameterNotFound
aws ec2 create-tags --dry-run --resources i-0123456789abcdef0 --tags Key=probe,Value=probe  # expect: UnauthorizedOperation, not DryRunOperation
aws ec2 run-instances --dry-run --image-id ami-0123456789abcdef0 --instance-type t3.micro  # expect: UnauthorizedOperation, not DryRunOperation
aws ssm start-session --target i-0123456789abcdef0  # expect: AccessDeniedException (the instance does not exist either)
```

As the host identity:

```sh
aws ssm send-command --document-name AWS-RunShellScript --instance-ids i-0123456789abcdef0 --parameters commands=id  # expect: AccessDeniedException (the instance does not exist either)
```

In each cluster, as the identity:

```sh
kubectl auth can-i get secrets --all-namespaces  # expect: no
kubectl auth can-i create pods/exec --all-namespaces  # expect: no
kubectl auth can-i create pods/portforward --all-namespaces  # expect: no
kubectl auth can-i get nodes/proxy  # expect: no
kubectl auth can-i create serviceaccounts/token --all-namespaces  # expect: no
kubectl auth can-i --list  # expect: no secrets; review what installed operators aggregated into view
```

## Known limits

- **Session ARNs in resource policies**: a resource-based policy that names the role's
  *session* ARN as its principal is not limited by the boundary. The guardrail's explicit
  denies still apply.
- **`ecs:DescribeTasks`** can show environment overrides passed at run time. ECS triage
  needs it, so it stays allowed. Redaction, which comes with the MCP server, is the control.
- **Host log lines** (`opscout-ReadOnly-ServiceLog`) can contain secrets that an
  application logged. No identity can prevent that, and redaction is the control there too.
- **Aggregation**: an operator can add resources to Kubernetes' `view` role. Only the live
  check shows it.

## Credentials for other systems

Each credential is read-only, limited to what the agents read, and stored in the OS
keychain. The configuration names only its keychain service, never the value.

| System | Choose | Never choose | Confirm |
|---|---|---|---|
| Observability (Datadog) | an application key with scopes, only `metrics_read`, `monitors_read`, `logs_read_data`, `events_read`, `apm_read`, created by a user or service account with a read-only role | any `*_write` scope, an unscoped key | the key's scopes page lists only read scopes |
| Code host (Bitbucket Cloud) | an API token with scopes: `read:pullrequest:bitbucket`, `read:repository:bitbucket`, `read:user:bitbucket` (as in [standup.md](standup.md)) | any `write:`, `admin:` or `delete:` scope | the token's page lists only the three read scopes |
| Tickets (Jira) | an API token with scopes: `read:jira-work`, `read:jira-user` | `write:jira-work`, `manage:jira-project`, `manage:jira-configuration` | the token's page lists only the two read scopes |
| Chat (Slack) | the app's bot scopes `chat:write`, `im:write` (as in [daemon.md](daemon.md)) | any `*:read` or `*:history` scope until the thread bot's spec | the app's OAuth page lists only those two |

## Refreshing the records

The maintainer refreshes the catalog and the managed-policy copies from AWS's public
reference, reviews the diff, and commits it:

```sh
uv run python -m tools.identity_refresh
opscout identity check
git diff --stat src/opscout/data/identity
```
