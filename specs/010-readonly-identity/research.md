# Research: Read-only identity

Checked on 2026-11-05 against AWS's official documentation (the Service Authorization
Reference and its JSON form, the AWS Managed Policy Reference, the IAM and IAM Identity
Center quotas, Systems Manager and EKS) and kubernetes.io. The maintainer's environment was
read for its shape only: Terraform, single sign-on, EKS with access entries, Linux hosts
under SSM, ECS, Lambda and RDS. No value from it enters this repository.

## R1. The action catalog (FR-011, FR-015)

**Facts**: AWS publishes the Service Authorization Reference as JSON at
`https://servicereference.us-east-1.amazonaws.com/`.

- **The index** is an array of `{service, serviceName, url, modified}`. On 2026-11-05 it
  listed 457 services, at `…/v1/<svc>/<svc>.json`.
- **Each service file** has `Name`, `Version` (`v1.5`), `Actions`, `Resources`,
  `ConditionKeys` and `Operations`.
- **Each action** carries `Annotations.Properties` with five booleans: `IsList`, `IsWrite`,
  `IsPermissionManagement`, `IsTaggingOnly` and `IsDataPlane`. All false means "Read". The
  flags are not mutually exclusive.
- **`IsDataPlane` is incomplete**: a missing flag means "not classified yet", as for
  `sqs:ReceiveMessage`.
- **Required resource types** appear only in the HTML pages, not in the JSON.

**Decision**:

- **The recorded catalog** is `catalog.json` inside the package (R7). It holds the source
  URL, the fetch date, each service's `Version`, and per service a map from action name to
  flag letters: `w` write, `p` permissions management, `t` tagging, `l` list, `d` data
  plane; an empty string means read. Actions are sorted, one per line, so a refresh shows
  up as a readable diff.
- **The refresh** is `uv run python -m tools.identity_refresh`, a development tool that is
  not shipped. It downloads the index and every service file and writes the catalog.
- **"Write" for the check** is any of `w`, `p` or `t`.
- **Measured on 2026-11-05**: 457 services and 22,444 actions, of which 12,695 are
  writes, 9,749 are reads, and 483 carry the `d` flag.
- **Data plane is not trusted alone.** It is incomplete, so the secret and data reads are a
  reviewed list (R4), and the `d` flag only adds to that list.

**Alternatives rejected**:

- **policy_sentry's or iam-dataset's scraped databases**: they are third-party copies of the
  same source, and would be a new dependency.
- **A live `iam:SimulatePrincipalPolicy` call**: it needs an account, which FR-014 forbids.

## R2. The guardrail cannot deny "every write" by pattern, so the cap does it (FR-002)

**Facts**:

- **Wildcards in the service prefix are unconfirmed.** The policy grammar documents wildcards
  only in the action name, plus the bare `"*"`. Nothing says that `"*:Get*"` is valid, so a
  `NotAction` list of read verbs across all services cannot be written.
- **Size limits**: a customer-managed policy may have at most 6,144 characters, whitespace
  excluded. A role's inline policies may have 10,240 combined. A permission set has one
  inline policy of at most 10,240 non-whitespace characters, and up to 25 managed policies
  (IAM's own default is 20 per role).
- **`ViewOnlyAccess`** (`arn:aws:iam::aws:policy/job-function/ViewOnlyAccess`, version v48,
  edited 2026-10-30) has 796 actions in 2 statements, so an explicit allow-list of the same
  reach would not fit in one policy.
- **A permissions boundary** can be AWS managed or customer managed, on a role and on a
  permission set. The effective permissions are the intersection of the identity policies
  and the boundary, and an explicit deny in either wins.

**Decision**: the read-only identity's cap is AWS's `ReadOnlyAccess` managed policy, used as
the permissions boundary. AWS keeps it to read actions, so a write that someone attaches
later by mistake still has no effect.

- **Recorded and proved**: like `ViewOnlyAccess`, it is recorded (R7), and the check proves
  from the catalog that it allows no write.
- **Gaps are closed by the guardrail**: any write it does allow, and every secret or data
  read it allows (such as `s3:GetObject` or `ssm:GetParameter`), is denied explicitly by the
  guardrail. The guardrail is a customer-managed policy attached to the identity, and its
  list is small (R4).

**Consequence**: `ssm:SendCommand` is a write, so the read-only identity cannot run host
commands. Host commands become a **separate, optional identity in the same account** (R5),
with its own customer-managed boundary that allows exactly the host capability. The spec's
US3 and FR-009 say "the host identity" accordingly. This also keeps the most powerful
capability off the identity that every agent uses.

**Alternatives rejected**:

- **A customer-managed boundary listing `ViewOnlyAccess`'s reach**: too large (above).
- **`ViewOnlyAccess` as the boundary**: it lacks log queries and the other capability reads.
- **No boundary**: an `Allow *` attached by mistake would then grant writes (US1, scenarios
  3 and 5).

**Measured on 2026-11-05**: the cap and the grant let through a few writes, all of which
the guardrail denies (R4, group `capped-writes`).

- **`ReadOnlyAccess` v191** expands to 7,059 catalog actions. Nine of them are writes:
  `athena:GetSessionEndpoint`, `backup:ListIndexedRecoveryPointsForSearch`,
  `billing:GetResourcePolicy`, `cognito-idp:GetClientToken`,
  `cognito-idp:GetTokensFromRefreshToken`, `iot:GetConnection`, `iot:ListSubscriptions`,
  `s3express:CreateSession` (conditionally) and `ssm-sap:GetResourcePermission`.
- **`ViewOnlyAccess` v48** expands to 2,006 actions. One is a write
  (`iot:ListSubscriptions`) and 21 are data plane.

**Known limit**: a resource-based policy that names the role *session* ARN as its principal
is not limited by the boundary. The guardrail's explicit denies still apply. This limit
belongs in the reference documentation.

## R3. Evaluation in the check (FR-011, FR-012)

**Facts**: AWS's evaluation order inside one account is: an explicit deny in any policy;
then an allow in the identity policies; then an allow in the boundary. Action names are
case-insensitive. Wildcards are `*` and `?`.

**Decision**: the check uses two evaluations, both sound by construction.

- **Exact.** For one request, an action and a resource ARN, the decision is "allow" when a
  statement in the identity policies allows it, a statement in the boundary allows it, and
  no statement denies it. This proves the declared reads (allowed on `*`) and the
  exceptions' probes (allowed on a catalog document; denied on `AWS-RunShellScript` and on
  an unknown document).
- **Robust.** For every catalog action, "may be allowed for some resource" is computed with
  one `Allow * on *` added to the identity policies, which models "anything attached by
  mistake". An action counts as denied only if a deny statement without conditions matches
  it on every resource (`Resource: "*"`), or if no boundary statement can allow it. Secret
  reads and writes must be denied under this evaluation.
- **Conservative conditions**: a statement with a `Condition` never counts as a deny, and
  always counts as a possible allow. So nothing that needs condition semantics is proved by
  accident.
- **Resource-scoped entries** (added after the review): a guardrail entry with a resource,
  such as `apigateway:GET` on `/apikeys/*`, counts as denied only when an unconditional deny
  names a resource that covers the entry's whole pattern. Covering is checked soundly: a
  `*` in the entry must fall inside a `*` of the deny. One probe that happens to be denied
  is no proof, because a narrowed deny (one region, one key) would pass it.
- **No wildcard in a service prefix**: an action such as `*:GetSecretValue` fails as
  "cannot prove", since IAM documents no such form (R2) and AWS may not honour it.
- **Duplicate keys** in JSON or YAML make a file unreadable (exit 2). Which value IAM, SSM
  or Kubernetes would keep is not something to rely on.
- **Fail closed**: a document using `Principal`, `NotPrincipal` or an unknown element fails
  the check as "cannot prove".
- **No wildcards in capability policies**: they list exact action names, so each name must
  be in the catalog (a typo fails). Undeclared grants (FR-012) are computed from these exact
  names. `ViewOnlyAccess` is the only grant with wildcards, and it belongs to the
  configuration capability by definition.

## R4. What the guardrail denies (FR-002, Q2)

**Decision**: the reviewed list lives in the package next to the catalog. The check proves
each entry denied under the robust evaluation.

| Group | Actions |
|---|---|
| Secret values | `secretsmanager:GetSecretValue`, `secretsmanager:BatchGetSecretValue`; `ssm:GetParameter`, `ssm:GetParameters`, `ssm:GetParametersByPath`, `ssm:GetParameterHistory`; `kms:Decrypt`, `kms:GenerateDataKey*`, `kms:ReEncrypt*` |
| Credential issuance | `sts:AssumeRole*`, `sts:GetFederationToken`; `ecr:GetAuthorizationToken`, `ecr-public:GetAuthorizationToken`, `codeartifact:GetAuthorizationToken`; `rds-db:connect`; `redshift:GetClusterCredentials*`, `redshift-serverless:GetCredentials`; `ec2:GetPasswordData` |
| Plaintext-secret reads (Q2) | `lambda:GetFunction`, `lambda:GetFunctionConfiguration`; `ecs:DescribeTaskDefinition`; `codebuild:BatchGetProjects`; `ec2:DescribeInstanceAttribute`, `ec2:DescribeLaunchTemplateVersions`, `ec2:GetConsoleOutput`; `glue:GetConnection`, `glue:GetConnections`; `cognito-idp:DescribeUserPoolClient`; `appsync:ListApiKeys`; `elasticbeanstalk:DescribeConfigurationSettings`; `apigateway:GET` on `/apikeys` and `/apikeys/*` only |
| Data plane | `s3:GetObject*`; `dynamodb:GetItem`, `dynamodb:BatchGetItem`, `dynamodb:Query`, `dynamodb:Scan`, `dynamodb:PartiQLSelect`; `sqs:ReceiveMessage`; `kinesis:GetRecords`; `rds-data:*`; `athena:GetQueryResults` |
| Sessions and shells | `ssm:StartSession`, `ssm:ResumeSession`, `ssmmessages:*`, `ssm-guiconnect:*`, `ec2-instance-connect:*`, `ssm:StartAutomationExecution`; `ssm:SendCommand` outside the catalog documents (R5) |

- **`apigateway:GET` is resource-scoped.** `ViewOnlyAccess` allows it on 40 listed paths and
  none of them is an API key, but the deny is still proved by an exact probe on
  `/apikeys`.
- **Catalog-proved rows**: the `d` flag adds any further allowed data-plane action as a
  failure, unless a capability declares it, as the log reads are declared.
- **Existence stays readable**: `ViewOnlyAccess` has no `secretsmanager` action and, for
  SSM, only `ListAssociations` and `ListDocuments`. A `secret-metadata` capability therefore
  grants `secretsmanager:ListSecrets`, `secretsmanager:DescribeSecret` and
  `ssm:DescribeParameters`, for ask and alert-triage. None of them returns a value.
- **Added in implementation** (measured, R2):
  - **Group `capped-writes`**: the writes that the two managed policies let through. The
    two Cognito token actions are listed under `credentials`.
  - **More `data-plane` entries**: the data-plane reads that `ViewOnlyAccess` grants, except
    the CloudWatch metric reads, which the metrics capability declares. These are object
    listing, Bedrock and agent sessions, feature-store records and workflow executions.
  - **A new failure kind**: an allowed data-plane action that no capability declares fails
    as `data-allowed`.
  - **Result**: the guardrail is 2,746 characters.
- **Added after the review**: more reads that return plaintext secrets. They are
  `lambda:ListFunctions` (each function's environment, so the configuration capability
  lists Lambda through `lambda:ListEventSourceMappings` and the infrastructure code instead),
  `autoscaling:DescribeLaunchConfigurations` (user data), the SageMaker model and job
  descriptions, `codebuild:BatchGetBuilds`, `batch:DescribeJobDefinitions` and
  `batch:DescribeJobs`, the Lightsail container services, `apprunner:DescribeService`, and
  the Amplify apps and branches. Usage-plan keys under API Gateway are denied as well. Over-denying is safe, and an
  entry that proves unnecessary can be removed by a reviewed change. The guardrail is now
  3,287 characters.
- **Residual risk**: `ecs:DescribeTasks` can show run-time environment overrides. ECS triage
  needs it (stopped reasons), so it stays allowed, and the reference documentation names
  this residual risk, which is left to redaction (ADR-0010, layer 4).

## R5. Host command documents (FR-007 to FR-009)

**Facts**:

- **`ssm:SendCommand` is a write.** It authorizes against the document ARN (required) and
  the target `instance` or `managed-instance` ARN.
- **Schema 2.2 parameters**: `interpolationType: ENV_VAR` exposes a parameter as
  `SSM_<name>` "to prevent command injection by treating parameter values as literal
  strings". `allowedValues` and `allowedPattern` are enforced at the API (Java regex) and on
  the agent (Go regexp).
- **Shell documents**: `AWS-RunShellScript` and `AWS-RunPowerShellScript` give a shell
  through SendCommand. Sessions (`ssm:StartSession`) use `SSM-SessionManagerRunShell` by
  default, and `AWS-StartSSHSession`, `AWS-StartInteractiveCommand` and the port-forwarding
  documents.

**Decision**: seven Command documents, schema 2.2, `aws:runShellScript`, Linux only. Each is
named after its file, with the `opscout-ReadOnly-` prefix:

| Document | Command (fixed) | Parameters |
|---|---|---|
| `Uptime` | `uptime; cat /proc/loadavg` | none |
| `Memory` | `free -m` | none |
| `Disk` | `df -hP -x tmpfs -x devtmpfs; df -iP -x tmpfs -x devtmpfs` | none |
| `TopProcesses` | `ps -eo pid,comm,%cpu,%mem --sort=-%cpu \| head -n 16; ps -eo pid,comm,%cpu,%mem --sort=-%mem \| head -n 16` | none |
| `ServiceState` | `systemctl show --property=ActiveState,SubState,MainPID,NRestarts,Result,ExecMainStartTimestamp -- "$SSM_ServiceName"` | `ServiceName`: `^[A-Za-z0-9@_][A-Za-z0-9@._-]{0,63}$`, `ENV_VAR` |
| `ServiceLog` | `journalctl --unit="$SSM_ServiceName" --lines="$SSM_Lines" --no-pager --output=short-iso` | `ServiceName` as above; `Lines`: `allowedValues` `50`, `100`, `200` |
| `ListeningPorts` | `ss -Hltn; ss -Hlun` | none |

- **Names only, never arguments**: `ps -o comm` prints process names without their
  arguments. `systemctl show` with named properties prints no command line, whereas
  `systemctl status` prints the process tree with arguments. `ss` without `-p` prints no
  process.
- **No leading `-` or `.`**: a service name cannot begin with `-` (an option) or `.`, so `..`
  and `-o` are refused, while `sshd.service` and `getty@tty1` pass.
- **No `{{ }}` interpolation**: no command uses it. Parameters arrive only as quoted
  environment variables after `--`.
- **The host identity's resources** (added after the review): every resource on which
  `ssm:SendCommand` is allowed, in the capability and in the boundary, must be exactly a
  catalog document ARN, or `instance/*` or `managed-instance/*`, all in the tree's single
  account. `NotResource` is refused. So no other document, no other account's shared
  document and no shell document can be added, whatever the guardrail says.
- **A trailing newline**: Java's `$` would accept `nginx\n`, but SSM Agent's Go regexp
  refuses it. Even if it got through, the value would arrive quoted as a literal unit name.
- **The check compares each instantiated document with the packaged reference**, as parsed
  data, so any added command or loosened pattern fails, named by document. In this
  repository, tests also prove each pattern against an injection corpus (`;`, `$( )`,
  backticks, `|`, `&`, `>`, newlines, `..`, `/`, spaces, quotes).
- **The host identity** has these documents:
  - `hosts/capability.json` allows `ssm:SendCommand` on exactly the catalog's document ARNs
    and on `instance/*` and `managed-instance/*` in the account. It also allows
    `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`, `ssm:ListCommands` and
    `ssm:DescribeInstanceInformation`.
  - `hosts/boundary.json` is the same allow list. It is the customer-managed boundary.
  - The shared guardrail is attached too.
- **Log lines can hold secrets**: no identity can prevent that. The documentation says so.

## R6. Clusters (FR-010)

**Facts**:

- **`AmazonEKSViewPolicy`** (`arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy`)
  "view[s] most Kubernetes resources". Its rules have no `secrets`, `pods/exec`,
  `pods/attach`, `pods/portforward` or `pods/proxy`.
- **`AmazonEKSAdminViewPolicy`** includes Secrets ("Note this includes Kubernetes
  Secrets"), and `AmazonEKSSecretReaderPolicy` grants them.
- **Kubernetes' `view` role** excludes Secrets, and its bootstrap rules include none of the
  five risky subresources. Operators can add to it through
  `rbac.authorization.k8s.io/aggregate-to-view`.
- **Kubernetes' own security guidance** warns that `nodes/proxy` and
  `serviceaccounts/token` are not read-only.

**Decision**: two reference documents.

- **`eks/access-policy.json`** has the shape of `aws eks associate-access-policy
  --cli-input-json`. The cluster is `example-prod`, the principal is
  `arn:aws:iam::123456789012:role/opscout-readonly`, the policy is
  `AmazonEKSViewPolicy`, and the scope is the cluster. The check requires that exact policy
  ARN.
- **`kubernetes/view-binding.yaml`** holds one `ClusterRoleBinding` from the group
  `opscout:readonly` to the `ClusterRole` `view`. The check refuses any other object and any
  other role reference.
- **The IAM side** is the cluster capability: `eks:DescribeCluster` and `eks:ListClusters`.
- **Subjects**: groups or users only, never a `system:` one, such as
  `system:unauthenticated`.
- **Aggregation** is only visible live (US4, scenario 3, and R9).

## R7. Where the documents live, and the commands (FR-001, FR-016, FR-017)

**Decision**: the reference tree ships inside the package at `src/opscout/data/identity/`,
so that `opscout identity check`, in another repository, compares against the version that
is installed. It holds:

- `catalog.json`, the action catalog (R1)
- `managed/ViewOnlyAccess.json` and `managed/ReadOnlyAccess.json`, the recorded copies of
  the two managed policies (R2)
- `guardrail-actions.json`, the reviewed list (R4)
- `aws/guardrail.json`
- `aws/readonly/capabilities/{secret-metadata,metrics,logs,changes,cost,cluster}.json`
- `aws/hosts/capability.json` and `aws/hosts/boundary.json`
- `ssm/opscout-ReadOnly-*.yaml`
- `eks/access-policy.json`
- `kubernetes/view-binding.yaml`

**What the layout means**:

- **The read-only identity** is `ViewOnlyAccess`, every file in `capabilities/` and the
  guardrail, under the `ReadOnlyAccess` boundary.
- **The host identity** is `hosts/capability.json` and the guardrail, under
  `hosts/boundary.json`.
- **Leaving out a capability** means deleting its file. Deleting `aws/hosts/` and `ssm/`
  leaves out host commands, and deleting `eks/` and `kubernetes/` leaves out clusters
  (FR-006). An unknown file fails the check.
- **The managed copies, the catalog and the reviewed list** are always read from the
  package, never from the checked directory, so an instantiated copy cannot weaken them.

**The only placeholders are** the account `123456789012` (in host-identity ARNs and in the
EKS principal), the cluster `example-prod` and the role names. The check accepts any
12-digit account, used consistently, and any cluster or role name. Leaving a placeholder
unfilled is legal.

**The commands** (contracts/commands.md):

- `opscout identity export DIR` writes the tree for instantiation (the five editable
  groups, not the package-owned records).
- `opscout identity check [DIR]` checks a directory, or the packaged reference when `DIR` is
  omitted.
- `.pre-commit-hooks.yaml` gains `opscout-identity-check`.

**Packaging**: uv_build puts the files under `src/opscout/` into the wheel. A task confirms
that by building the wheel and listing it.

**Alternatives rejected**:

- **`deploy/identity/`** (PLAN.md §6): outside the package, so an installed opscout could
  not read it. PLAN.md §6 is updated.
- **A Terraform module**: the maintainer's tool, but it would make opscout depend on one
  tool. Terraform loads JSON and YAML with `file()`, and the documentation shows it.

## R8. Size and attachment (FR-005)

**Decision**: the check measures every editable AWS document, without whitespace, against
6,144 characters (customer managed). It also measures the sum of the guardrail and the
capabilities against 10,240, for anyone who inlines them in a permission set. The
attachment count is checked against 20 per identity: one managed copy, six capabilities
and the guardrail make 8.

## R9. The live check (FR-018)

**Decision**: `docs/reference/identity.md` gives two kinds of probe. None of them can change
anything.

- **Simulation by an administrator**: `aws iam simulate-principal-policy` against the
  instantiated role. It evaluates the real attached policies and the boundary, and changes
  nothing. Every guardrail group must be denied, a sample of writes across services must be
  denied, and every declared read must be allowed.
- **Probes as the identity**:
  - `secretsmanager get-secret-value` on a secret that does not exist, and `ssm
    get-parameter --with-decryption` on a name that does not exist: both expect
    `AccessDenied`, not `ResourceNotFound`.
  - `ec2 create-security-group --dry-run` and `ec2 create-key-pair --dry-run`, with no
    resource ID: both expect `UnauthorizedOperation`, not `DryRunOperation`. (Corrected by
    the live check on 2026-11-06: the first choice, `create-tags` and `run-instances` with
    fake instance and image IDs, failed EC2's ID validation before the permission check.)
  - `ssm start-session` on an instance ID that does not exist: expects `AccessDenied`.
  - For the host identity, `ssm send-command` with `AWS-RunShellScript`, aimed at an
    instance ID that does not exist: expects `AccessDenied`.
  - In each cluster, `kubectl auth can-i get secrets`, `create pods/exec`,
    `create pods/portforward`, `get nodes/proxy` and `create serviceaccounts/token` must all
    answer `no`. `kubectl auth can-i --list` shows what aggregation added.

## R10. Credentials for the other systems (FR-019)

**Decision**: guidance only, in `docs/reference/identity.md`, with each item in the keychain
under a name that the configuration references:

- **Observability (Datadog)**: an application key restricted to read scopes (metrics,
  monitors, logs, events, APM), created by a user or service account with a read-only role.
  Never `*_write` scopes.
- **Code host**: spec 009's three read scopes.
- **Tickets (Jira)**: an API token with scopes, only `read:jira-work` and `read:jira-user`.
- **Chat**: spec 008's `chat:write` and `im:write`, and nothing more until the thread bot's
  spec.
