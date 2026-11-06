# Feature Specification: Read-only identity

**Feature Branch**: `feat/010-readonly-identity`

**Created**: 2026-11-05

**Status**: Draft

**Input**: User description: "readonly-identity (Phase 2, PLAN.md §7, need 1–3; ADR-0010 layer
1 and the host part of layer 2). Ship, in this public repo and with fake IDs only, the
reference read-only identity that the investigation agents (alert triage, cost triage, ask)
will use against real systems: an AWS IAM policy set that grants view-only access (including
Cost Explorer reads) with explicit denies on secret-value APIs (Secrets Manager
GetSecretValue, SSM GetParameter(s) with decryption, KMS Decrypt, and similar) and on every
mutation; a Kubernetes binding to the built-in `view` role, which excludes Secrets;
allow-listed host command documents (SSM documents that run only fixed read-only commands,
never a generic run-shell document); and guidance for the read-only observability key and
code-host/ticket tokens. The policies are templates the user's employer instantiates in their
own IaC repo (who applies them stays an open item, PLAN.md §9); the engine never applies
them. Exit criterion: policy checks show that secret reads and mutations are denied, tested
in code (e.g. policy simulation or static analysis of the documents) without a real account;
the live check with a sandbox account is a manual step the user runs. Non-goals: applying the
policies, creating accounts or roles, the MCP server (next spec ops-mcp-server), any real
account ID, profile or hostname."

## Context

Phase 2's agents (alert triage, cost triage, "is X configured?") read untrusted text, such as
alert bodies, log lines and chat threads, while they hold access to real systems. ADR-0010
puts the main guarantee in the identity they use: if an injected instruction takes over the
model, the identity still cannot change anything or read a secret's value (Constitution
Principles II and III). Until that identity exists, PLAN.md says that every run against a
real system waits (§7, Phase 2).

This feature ships the reference identity as documents with placeholders, written so that it
can be checked: AWS permissions for one environment's account, a cluster view level for
Kubernetes, and a catalog of host command documents that run fixed read-only commands. A
check in code proves the two properties that matter: every secret read and every mutation is
denied, and every read an agent needs is allowed. It runs without an AWS account. The
employer's infrastructure-as-code repository instantiates the documents. The engine never
applies them, and a documented live check in a sandbox account confirms the result.

The reference fits the maintainer's environment, described here only by its shape. Each
environment has its own AWS account, reached through single sign-on. There are Kubernetes
clusters on EKS, granted through access entries; Linux hosts (Ubuntu and Amazon Linux) that
are managed by SSM; ECS services; Lambda functions; and RDS databases. The
infrastructure-as-code is Terraform. The documents use no Terraform-only form, so other
tooling can load them.

## Clarifications

### Session 2026-11-05

- Q: How is configuration metadata granted? → A: through AWS's maintained view-only policy,
  under the guardrail and the cap on maximum permissions. A recorded copy of the policy's
  current version lets the check evaluate it offline, and a new version is a reviewed
  refresh, like the action catalog (FR-004, FR-011, FR-015).
- Q: What about reads that return plaintext secrets (function and task environments, user
  data, connection passwords, client secrets, API key values)? → A: the guardrail denies
  them. "Is X configured?" answers about those values from the infrastructure code, not from
  the deployed resources (FR-002).
- Q: Does opscout ship a way to check the instantiated copy? → A: yes. A command checks a
  directory of instantiated documents, and a pre-commit hook runs it in the infrastructure
  repository, like spec 002's hook for the private configuration. The instantiated
  documents stay files the infrastructure tool loads (FR-016).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Proof in code that the identity cannot write or read a secret (Priority: P1)

The maintainer changes a reference document. The check evaluates the whole AWS permission set
the way AWS does for identity policies: an explicit deny wins, then an allow, and anything
else is denied. It runs over every action AWS publishes. Every secret-value read, every
credential issuance and every action that AWS classifies as a write, a permissions change or
tagging is denied, except a short, named list of exceptions, each with its reason and its
narrowed resources. Every read that an agent's declared capability needs is allowed. The
check fails, naming the action and the statement, when either property breaks.

**Why this priority**: this is the plan's exit criterion and the guarantee ADR-0010 relies
on. Without it, the documents are only a promise.

**Independent Test**: run the check on the reference documents, then on copies with one
planted fault each (a removed deny, a wildcard allow, a missing read). The first passes; each
copy fails with its fault named.

**Acceptance Scenarios**:

1. **Given** the reference documents, **When** the check runs, **Then** it reports that 100 %
   of the secret-value and credential actions in its catalog are denied, that every write,
   permissions-management and tagging action is denied or is a named exception, and that every
   declared read is allowed.
2. **Given** a copy whose deny statement for secret values is removed, **When** the check
   runs, **Then** it fails and names `secretsmanager:GetSecretValue` and the other actions
   that are now allowed.
3. **Given** a copy that adds `"Action": "*"` with `"Effect": "Allow"`, **When** the check
   runs, **Then** it still passes the deny properties, because the guardrail holds, and
   reports the grant as undeclared, which is a failure.
4. **Given** a copy that denies a read a capability declares, such as
   `cloudwatch:GetMetricData`, **When** the check runs, **Then** it fails and names the
   capability that loses it.
5. **Given** a copy that adds a policy granting a mutation outside the guardrail, as an
   administrator might do by mistake, **When** the check evaluates the identity with its cap
   on maximum permissions, **Then** the mutation is still denied.
6. **Given** an action AWS published after the recorded catalog, **When** the catalog is
   refreshed, **Then** the check classifies it by its access level, and a new write action is
   denied without any edit to the documents.

---

### User Story 2 - The identity grants what the agents need, and says why (Priority: P1)

Each permission the identity grants belongs to a named capability: what it is for, which
planned agents use it, and its actions. The capabilities are viewing configuration
metadata, metrics and alarms, log queries, recent changes (the audit trail and deployments),
cost and usage, cluster access, and host commands. The person who instantiates the identity
reads the capabilities and fills the placeholders: the account, the environment name and the
role or permission-set name. They can leave out a capability that their environment does not
use.

**Why this priority**: Constitution Principle II says that every integration declares the
permissions it needs and that the identity grants nothing beyond them. The agents of the
next specs build on this list.

**Independent Test**: from the documents and the capability list, the check confirms that
every allowed action belongs to a declared capability, and that removing a capability
removes its actions and nothing else.

**Acceptance Scenarios**:

1. **Given** the capability list, **When** it is read, **Then** each capability states its
   purpose, the planned agents that use it and its actions, with no organization-specific
   value.
2. **Given** the documents, **When** the check runs, **Then** every allowed action maps to
   at least one declared capability, and an action that maps to none fails the check.
3. **Given** an environment without Kubernetes, **When** the person leaves the cluster
   capability out, **Then** the remaining documents still pass the check.
4. **Given** the documents, **When** each is measured, **Then** it fits AWS's size limits for
   a customer-managed policy and for an SSO permission set, so it can be attached either way.

---

### User Story 3 - Hosts run only allow-listed commands (Priority: P2)

To look at a host, an agent can only run a document from a fixed catalog. Each document runs
fixed, read-only commands: load and uptime, memory, disk usage, the processes that use the
most CPU or memory (names only, without arguments), the state of a named service, the last
lines of a named service's log, and the listening ports. Any parameter is constrained to a
pattern, such as a service name or a bounded line count, so it cannot carry a command. The
identity can send only these documents. An interactive session, a generic shell document, an
automation and a temporary SSH key are all denied.

**Why this priority**: hosts are where a shell would turn an injected instruction into an
action (ADR-0010, layer 2). Alert triage needs host facts, but it comes after US1 and US2.

**Independent Test**: the check reads each document and confirms that its commands are in a
fixed list, that every parameter has a restrictive pattern, and that the permission set lets
the identity send only these documents.

**Acceptance Scenarios**:

1. **Given** the catalog, **When** the check reads it, **Then** each document targets Linux,
   runs only commands from the allowed list, and has no parameter that is free text.
2. **Given** a service-name parameter set to `nginx; rm -rf /` or `$(id)`, **When** it is
   checked against the document's pattern, **Then** the pattern rejects it.
3. **Given** the permission set, **When** the check evaluates sending the generic shell
   document, the PowerShell document or any document outside the catalog, starting a
   session, starting an automation, or pushing an SSH key, **Then** each is denied.
4. **Given** a planted document whose commands print environment variables or read a file
   given as a parameter, **When** the check runs, **Then** it fails and names the document.

---

### User Story 4 - Clusters show everything except secrets (Priority: P2)

The identity reaches each EKS cluster through an access entry with the view level that
excludes Secrets. A reference manifest also binds a group to Kubernetes' built-in `view`
role, for clusters that map identities through RBAC. Neither form allows reading Secrets,
`exec`, `attach`, port-forwarding, the node proxy, or creating service-account tokens.

**Why this priority**: the maintainer's environment runs EKS, but cluster triage comes after
the AWS side.

**Independent Test**: the check reads the access-entry document and the binding manifest,
and confirms the view level, the built-in role and the absence of any extra rule.

**Acceptance Scenarios**:

1. **Given** the access-entry reference, **When** the check reads it, **Then** it names the
   EKS view policy that excludes Secrets, and never the administrator-view or edit policy.
2. **Given** the binding manifest, **When** the check reads it, **Then** it binds only the
   built-in `view` role, and no additional role grants `secrets`, `pods/exec`,
   `pods/attach`, `pods/portforward`, `nodes/proxy` or `serviceaccounts/token`.
3. **Given** a cluster whose installed operators add resources to `view` through
   aggregation, **When** the live check runs, **Then** it lists what the identity can read
   and flags anything secret-like (US5).

---

### User Story 5 - The person who applies it can confirm it worked (Priority: P3)

After the employer's repository instantiates the documents, a person confirms two things.
First, their copy still keeps the guarantees: a command runs the same check on a directory
of instantiated documents, and a pre-commit hook runs it on every commit in the
infrastructure repository. Second, in a sandbox account, the live identity really denies. The
documented live check uses only probes that cannot change anything: a secret read on a
secret that does not exist, writes with AWS's dry-run flag, a session start on an instance
that does not exist, and Kubernetes' "can I" queries. Each probe expects "access denied".

**Why this priority**: it closes the loop between the reference and what actually runs, but
it depends on someone applying the documents, which is outside this repository.

**Independent Test**: follow the live-check document against a sandbox account with the
instantiated identity, and record each probe's outcome in this spec's Actuals.

**Acceptance Scenarios**:

1. **Given** the live-check document, **When** it is read, **Then** every probe is one that
   AWS or Kubernetes refuses before acting, so none can change anything even if the identity
   were wrong.
2. **Given** a correctly instantiated identity in a sandbox account, **When** the person runs
   the probes, **Then** every secret read, write and session probe returns access denied,
   and every declared read probe succeeds.

---

### User Story 6 - Tokens for the other systems are read-only too (Priority: P3)

The reference also says how to create the other credentials the agents will use, each
read-only and limited to what they read: the observability key, the code-host token, the
ticket-system token and the chat app. It also says where each one lives: in the keychain,
named by the configuration, never in it.

**Why this priority**: those systems are reached later (ops-mcp-server and the agents). The
guidance belongs with the identity, but nothing enforces it in code here.

**Independent Test**: a reader follows the guidance and finds, for each system, the scopes
or role to choose, the ones never to choose, and how to confirm the result.

**Acceptance Scenarios**:

1. **Given** the guidance, **When** it is read, **Then** each system lists the read scopes to
   select and the write or administrative scopes to leave out, and the code-host and chat
   entries match what specs 008 and 009 already ask for.

---

### Edge Cases

- **Reads that return a secret in plaintext.** Some read actions return values that are
  often secrets: a Lambda function's environment variables, an ECS task definition's
  environment, a CodeBuild project's environment, an EC2 instance's or launch template's user
  data, a Glue connection's password, a Cognito client's secret, an API Gateway key's value.
  The guardrail denies these reads, so the agents answer questions about such values from
  the infrastructure code instead. Finding them is a reviewed list in the check, matched
  against the catalog. A future read that returns a secret is added to that list when it
  is found; it is not left to redaction.
- **Credential issuance looks like a read**, for example a container registry login token, a
  database authentication token, cluster credentials for a data warehouse, or a Windows
  instance's password. These count as secret reads and are always denied.
- **Assuming another role** would escape the identity. Assuming any role is denied.
- **Data-plane reads**: object contents in S3, table items, queue messages (receiving one
  hides it from its consumer), stream records and SQL through a data API. These are denied.
  The agents read metadata, metrics and logs, not application data.
- **Parameter values**: reading any SSM parameter's value is denied, whether it is plain or
  encrypted. Its existence and metadata stay readable, so the agents report that a parameter
  exists and where (Principle III).
- **A permission-set or policy size limit** is reached as capabilities grow: the check
  measures each document, and a capability is split rather than its actions widened.
- **Wildcards**: an allow with a wildcard can grow when AWS adds actions. The documents allow
  only exact actions or prefixes the check expands against the recorded catalog. A
  catalog refresh that widens a prefix to a new write action is caught, because writes are
  denied.
- **The recorded catalog is old**: an action missing from the catalog cannot be proved. The
  check names the catalog's date, and the guardrail denies every write by access level, not
  by a list.
- **Host log lines can hold secrets**: the identity cannot prevent a log line from
  containing a secret. Redaction (ADR-0010, layer 4) is the later control, and the live-check
  document says so.
- **Aggregated cluster roles**: an operator can add resources to `view`. Only a live query
  shows them (US4, scenario 3).
- **Windows hosts**: there are no documents for them, and the PowerShell document is denied.

## Requirements *(mandatory)*

### Functional Requirements

#### The reference documents

- **FR-001**: The repository MUST ship the reference identity as documents with placeholders
  for the account, the environment and the identity's name. They MUST use only reserved fake
  values (Principle I), and MUST be loadable by any infrastructure tool.
- **FR-002**: The AWS documents MUST consist of capability grants, one per declared
  capability; a guardrail that explicitly denies secret-value reads, credential issuance,
  role assumption, data-plane reads, reads that return plaintext secrets (edge cases),
  sessions and shells, and every write,
  permissions-management and tagging action except the named exceptions; and a cap on
  maximum permissions, so that a policy attached later by mistake cannot add a mutation or
  a secret read.
- **FR-003**: Each named exception to "every write is denied" MUST state its reason and
  narrow its resources. The known exceptions are sending a catalog document to managed
  instances, and starting and stopping read-only log queries if AWS classifies them as
  writes.
- **FR-004**: The capabilities MUST be listed with their purpose, the planned agents that use
  them and their actions: configuration metadata, metrics and alarms, log queries, recent
  changes, cost and usage, cluster access, and host commands. Configuration metadata is
  AWS's maintained view-only policy, attached by reference. The other capabilities are
  explicit action lists maintained here.
- **FR-005**: Every document MUST fit AWS's size limits both as a customer-managed policy and
  inside an SSO permission set.
- **FR-006**: Leaving out an optional capability (cluster access, host commands) MUST leave a
  set of documents that still passes the check.

#### Hosts

- **FR-007**: The repository MUST ship a catalog of host command documents for Linux. They
  cover load and uptime, memory, disk usage, the top processes by CPU and by memory (names
  only), a named service's state, a named service's last log lines (at most a bounded
  number), and listening ports (without process arguments).
- **FR-008**: Every catalog document parameter MUST be constrained to a pattern or a fixed
  list of values that cannot express a shell metacharacter, a path or a command. No document
  may print environment variables, read a file named by a parameter, or run a command
  outside the allowed list.
- **FR-009**: The AWS documents MUST let the identity send only catalog documents, and MUST
  deny the generic shell and PowerShell documents, sessions, automations and temporary SSH
  keys.

#### Clusters

- **FR-010**: The repository MUST ship a reference EKS access entry with the view level that
  excludes Secrets, and a Kubernetes manifest that binds a group only to the built-in `view`
  role.

#### The check

- **FR-011**: A check MUST evaluate the AWS documents as AWS evaluates identity policies
  (explicit deny, then allow, otherwise deny), including the cap on maximum permissions,
  action wildcards, resources and the conditions the documents use. It MUST evaluate them
  over a recorded catalog of every AWS action with its access level, and over a recorded
  copy of the AWS-maintained view-only policy's current version. The source, version and
  date of each MUST be recorded.
- **FR-012**: The check MUST fail, naming the action, the statement and the capability, when
  a listed secret or credential action is allowed; when a write, permissions-management or
  tagging action is allowed and is not a named exception within its resources; when a
  declared read is not allowed; or when an allowed action belongs to no capability.
- **FR-013**: The check MUST verify the host catalog (FR-007, FR-008) and the cluster
  references (FR-010), naming the offending document and line.
- **FR-014**: The check MUST run offline in the test suite and in CI, with no AWS account,
  network access or credentials, and MUST finish within the suite's usual time.
- **FR-015**: Refreshing the recorded catalog or the view-only policy copy MUST be a
  reviewed change. The diff MUST show the added actions and their access levels, and the
  check MUST pass on the new records before merge.
- **FR-016**: A command MUST run the same check on a directory of instantiated documents,
  read only and offline, with an exit status for pass and fail. The repository's pre-commit
  hook definitions MUST offer it to an infrastructure repository, as spec 002 offers the
  configuration check. The placeholders that may stay unfilled MUST be named, and a
  real-looking value MUST NOT be required.

#### Guidance and live check

- **FR-017**: The documentation MUST explain how to instantiate the documents. It MUST
  include an example for an IAM role and for an SSO permission set, with fake values. It
  MUST say which capabilities are optional, and that the engine never applies anything.
- **FR-018**: The documentation MUST hold the live check: probes that cannot change anything,
  each with its expected outcome, for a sandbox account and a cluster.
- **FR-019**: The documentation MUST give the read-only credential guidance for the
  observability key, the code-host token, the ticket-system token and the chat app, and the
  keychain rule for each.

#### Proof

- **FR-020**: Tests MUST cover each acceptance scenario and edge case, with planted faults
  for every failure FR-012 and FR-013 name, and the traceability of every requirement to a
  test.
- **FR-021**: Once an identity is instantiated in a sandbox account, the live check's
  outcomes MUST be recorded in this spec's Actuals and in PLAN.md. This is a manual step and
  is not a gate for merge.

### Key Entities

- **Capability**: a named group of read permissions, with a purpose and the planned agents
  that use it. It is the unit the identity grants and the agents declare.
- **Guardrail**: the explicit denies and the cap on maximum permissions that hold whatever
  else is attached.
- **Exception**: a write action the identity needs, with its reason and narrowed resources.
- **Action catalog**: AWS's published list of actions with their access levels, recorded
  with its source and date.
- **Host command document**: a fixed, read-only command set with constrained parameters,
  which the identity may send to managed instances.
- **Probe**: one live-check request that cannot change anything, with its expected outcome.

## Non-Goals

- **Never apply anything**: the engine does not create, attach or change accounts, roles,
  permission sets, policies, access entries, bindings or documents. The employer's
  infrastructure repository does.
- **Never hold a real value**: no account ID, profile, role ARN, cluster, hostname or
  instance in this repository.
- **The MCP server, its tools and redaction** are ops-mcp-server (PLAN.md §7). Choosing
  which agent uses which capability at run time belongs to the agents' specs.
- **Windows hosts, other clouds and other Kubernetes distributions**: later, with a user.
- **Probes that could change something** if the identity were wrong: none in the live check.
- **Who applies the identity** stays an open item (PLAN.md §9).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the reference documents, the check proves that 100 % of the catalog's
  secret-value and credential actions are denied, and that 100 % of its write,
  permissions-management and tagging actions are denied outside the named exceptions.
- **SC-002**: Every planted fault in the test corpus is caught, and the failure names the
  action or document responsible.
- **SC-003**: Every action a capability declares is allowed, and every allowed action belongs
  to a capability.
- **SC-004**: The check runs offline and adds less than 10 seconds to the test suite.
- **SC-005**: A person instantiates the identity for one environment from the documentation
  alone, without reading this repository's code.
- **SC-006**: In the live check, every secret, write and session probe returns access denied
  and every read probe succeeds. This is recorded after an identity exists.

## Assumptions

- **One identity per environment**, each in its own AWS account, reached through single
  sign-on or a role (ADR-0010). Cross-account access is not part of the identity.
- **AWS publishes its actions and their access levels** in a machine-readable form that the
  check can record. AWS's classification is the source of truth for "write"; the plan pins
  the source.
- **Linux hosts managed by SSM** and **EKS with access entries**, as in the maintainer's
  environment. RBAC-mapped clusters get the binding manifest.
- **The agents read metadata, metrics, logs, cost and host state, not application data.** A
  later spec that needs application data changes this spec first.
- **The redaction layer** (ADR-0010, layer 4) is built with ops-mcp-server. Until then, no
  agent runs against real systems.
