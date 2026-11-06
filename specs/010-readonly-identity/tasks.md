---
description: "Tasks for the read-only identity (spec 010)"
---

# Tasks: Read-only identity

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/commands.md](contracts/commands.md),
[contracts/documents.md](contracts/documents.md), [quickstart.md](quickstart.md)

**Tests**: mandatory and first. Each test is marked `@spec("FR-0NN")`, bound to `"010"`,
with one requirement per decorator, because the traceability test reads them. Small
hand-written policies test the evaluator. Planted-fault copies of the reference tree test the
proofs. No test uses the network or an AWS account.

## Phase 1: Setup

- [ ] T001 Confirm the baseline on `feat/010-readonly-identity`: `uv run just fast` passes
- [ ] T002 Write failing tests in `tests/unit/identity/test_refresh.py` (FR-011, FR-015),
  using two trimmed service files and an index saved under
  `tests/unit/identity/samples/service-reference/`, in the shapes of research R1. They
  cover:
  - `Annotations.Properties` maps to the flag letters (`IsWrite`→`w`,
    `IsPermissionManagement`→`p`, `IsTaggingOnly`→`t`, `IsList`→`l`, `IsDataPlane`→`d`;
    all false → `""`)
  - a missing `IsDataPlane` adds nothing
  - actions are sorted
  - `source`, `fetched` and each service's `version` are written
  - the diff summary lists actions added, removed or reclassified
  - a managed-policy page's JSON block parses into `{arn, version, fetched, document}`
- [ ] T003 Implement `tools/identity_refresh.py`: it downloads
  `https://servicereference.us-east-1.amazonaws.com/` and every service file, plus the
  `ViewOnlyAccess` and `ReadOnlyAccess` pages of the AWS Managed Policy Reference, using
  `urllib` with `truststore`. It writes `src/opscout/data/identity/catalog.json` and
  `src/opscout/data/identity/managed/{ViewOnlyAccess,ReadOnlyAccess}.json`, and prints the
  diff summary. T002 passes. Run it once and commit the records. Record the service count,
  the action count and both versions in research R1 and R2.

## Phase 2: Foundational — types, parsing, records

- [ ] T004 Create `tests/unit/identity/test_traceability.py`: every requirement from FR-001
  to FR-021 has a test marked with it. This test is marked FR-020, and is
  `xfail(strict=True)` until T040.
- [ ] T005 [P] Write failing tests in `tests/unit/identity/test_parse.py` (FR-011). They
  cover:
  - a policy parses when it has `Version` `2012-10-17` and `Statement` as a list or a single
    statement, each with `Sid` (optional), `Effect` `Allow`|`Deny`, exactly one of
    `Action`/`NotAction` and exactly one of `Resource`/`NotResource`, and `Condition` kept
  - `Principal`, `NotPrincipal`, another `Version`, an unknown key, both `Action` and
    `NotAction`, or neither, each give `cannot-prove` with `<file>#<index or Sid>`
  - YAML and JSON load errors name the file and the line
- [ ] T006 Write `src/opscout/core/identity.py` with these types: `Statement`, `Policy`,
  `Identity` (its policies and boundary), `Capability`, `Catalog` (lookup is
  case-insensitive on prefix and name; `is_write` is any of `w p t`), `Request`, `Decision`,
  `Finding` with the kinds from data-model.md, and `Report`. Add the parsing in
  `src/opscout/adapters/identity_files.py`: it reads a tree and the package data through
  `importlib.resources`. T005 passes.
- [ ] T007 [P] Write failing tests in `tests/unit/identity/test_catalog.py` (FR-011). The
  packaged catalog loads. It has more than 400 services. Its `fetched` date and `source` are
  set. `ssm:SendCommand` and `athena:StartQueryExecution` are writes. `logs:StartQuery`,
  `ce:GetCostAndUsage` and `sqs:ReceiveMessage` are reads (research R1, from the verified
  facts). Both managed copies carry `arn`, `version` and `document`.

## Phase 3: User Story 1 — proof that the identity cannot write or read a secret (P1, MVP)

**Goal**: the exact and robust evaluations, the guardrail and the cap. The proofs fail on
every planted fault.
**Independent test**: the reference passes, and each planted copy fails with its fault
named.

- [ ] T008 [P] [US1] Write failing tests in `tests/unit/identity/test_evaluator.py`
  (FR-011, research R3).
  - **Exact evaluation**: a deny beats an allow. Without an allow, the request is denied
    implicitly. An allow must exist in both the identity policies and the boundary.
  - **Wildcards**: `*` and `?` work in actions (case-insensitive) and in resources
    (case-sensitive). `NotAction` and `NotResource` are honoured.
  - **SendCommand** is two requests that must both be allowed.
  - **Robust evaluation**: an action counts as denied only by a deny with no `Condition` on
    `Resource: "*"`, or when no boundary statement can allow it. `Allow *` is added.
  - **Conditions are conservative**: a `Condition` never counts as a deny and always counts
    as a possible allow.
  - **Decisions carry statement refs.**
- [ ] T009 [US1] Implement the two evaluations in `src/opscout/core/identity.py`, with
  patterns precompiled. T008 passes.
- [ ] T010 [P] [US1] Write `src/opscout/data/identity/guardrail-actions.json`: the groups
  `secret-values`, `credentials`, `plaintext-secrets`, `data-plane` and `sessions`, each
  entry `{action, resource, why}`, exactly the table in research R4. Write
  `src/opscout/data/identity/aws/guardrail.json` with its deny statements, in the form of
  contracts/documents.md. Keep it at most 6,144 characters without whitespace.
- [ ] T011 [P] [US1] Write failing tests in `tests/unit/identity/test_reference.py` on the
  packaged tree.
  - FR-002: under the robust evaluation, every guardrail entry is denied for the read-only
    identity and for the host identity. The resource-scoped `apigateway:GET` on `/apikeys`
    is denied by an exact probe.
  - FR-002: every write in the catalog is denied for the read-only identity under the robust
    evaluation.
  - FR-012: no `d`-flagged action is allowed unless a capability declares it.
  - FR-014: the check needs no network (sockets are blocked in the test), and the whole
    proof runs in under 2 seconds.
  - FR-012: the report counts match the catalog.
- [ ] T012 [P] [US1] Write failing tests in `tests/unit/identity/test_faults.py` (FR-012,
  FR-020, US1 scenarios 2 to 6). Build each fault from the packaged tree in a temporary
  directory:
  - delete `DenySecretValues` → `secret-allowed`, naming `secretsmanager:GetSecretValue` and
    the others
  - add an `Allow *` file → the deny properties still pass, and `layout` or
    `undeclared-grant` fails
  - replace the boundary with an `Allow *` → `write-allowed`
  - add a capability that allows `ec2:CreateTags` while the cap still holds → no
    `write-allowed`
  - a catalog with a new write action, given as a fixture → denied with no edit
  - a `Condition` on a guardrail deny → `secret-allowed`, because conditional denies don't
    count
- [ ] T013 [US1] Implement the proofs in `src/opscout/services/identity.py`:
  `prove(tree, records) -> Report`, covering the guardrail, the writes, the data plane and
  the counts. Then wire the read-only identity: the `ViewOnlyAccess` copy, the capabilities
  and the guardrail, under the `ReadOnlyAccess` boundary (research R7). If the cap's copy
  allows a write, add an explicit deny to the guardrail and record it in research R2. T011
  and T012 pass.

## Phase 4: User Story 2 — capabilities, declared and sized (P1)

**Goal**: every grant belongs to a declared capability. Every declared read is allowed. Every
document fits.
**Independent test**: the reference passes. An undeclared or unknown action, a missing read,
or an oversized document each fails.

- [ ] T014 [P] [US2] Write `src/opscout/data/identity/capabilities.json` per data-model.md:
  `name` is one of `configuration`, `metrics`, `logs`, `changes`, `cost`, `cluster`,
  `hosts`; plus `purpose`, `agents` (any of `alert-triage`, `cost-triage`, `ask`),
  `identity` `readonly`|`hosts`, `optional` (true for `cluster` and `hosts`), `grant`
  `managed`|`actions`, `actions` (exact `service:Action` names, no wildcards) and `reads`.
  Write `src/opscout/data/identity/aws/readonly/capabilities/{metrics,logs,changes,cost,cluster}.json`
  to match.
- [ ] T015 [P] [US2] Write failing tests in `tests/unit/identity/test_capabilities.py`:
  - FR-004: every declaration has a purpose, its agents and its actions. `configuration` is
    `grant: managed` with the `ViewOnlyAccess` ARN. No value in it is organization-specific.
  - FR-004: every `reads` entry is allowed by the exact evaluation, otherwise
    `read-missing`, naming the capability and the denying statement.
  - FR-012: every action allowed by a capability file is in its declaration, otherwise
    `undeclared-grant`. Every name is in the catalog, otherwise `unknown-action`. Wildcards
    in a capability file fail.
  - FR-006: deleting `cluster.json`, or `aws/hosts/` with `ssm/`, or `eks/` with
    `kubernetes/`, still passes. Deleting `metrics.json` fails `layout`. An unknown file
    fails `layout`.
  - FR-001: the only account is `123456789012`, the only cluster is `example-prod`, and the
    only names are `opscout-*`. A tree that mixes two accounts fails `placeholder`.
- [ ] T016 [P] [US2] Write failing tests in `tests/unit/identity/test_sizes.py` (FR-005,
  research R8):
  - each AWS document has at most 6,144 non-whitespace characters
  - the guardrail plus the capabilities have at most 10,240
  - at most 20 attachments per identity
  - a padded copy fails `too-large`, naming the file and its size
- [ ] T017 [US2] Implement the declaration, read, undeclared, unknown-action, layout,
  placeholder and size proofs in `src/opscout/services/identity.py` and the layout rules in
  `src/opscout/adapters/identity_files.py`. T015 and T016 pass.

## Phase 5: User Story 3 — hosts run only allow-listed commands (P2)

**Goal**: seven fixed Linux documents and a separate host identity that can send only them.
**Independent test**: the reference documents match. Injection values are refused. Shell
documents and sessions are denied.

- [ ] T018 [P] [US3] Write the seven documents
  `src/opscout/data/identity/ssm/opscout-ReadOnly-{Uptime,Memory,Disk,TopProcesses,ServiceState,ServiceLog,ListeningPorts}.yaml`,
  exactly the commands and parameters of research R5:
  - schema `2.2`, `aws:runShellScript`, and the precondition `platformType` `Linux`
  - `ServiceName` uses `allowedPattern: "^[A-Za-z0-9@._-]{1,64}$"` and
    `interpolationType: ENV_VAR`
  - `Lines` uses `allowedValues` `["50", "100", "200"]` and `ENV_VAR`
  - no `{{` appears in any command
- [ ] T019 [P] [US3] Write `src/opscout/data/identity/aws/hosts/capability.json` and
  `boundary.json` per contracts/documents.md. `ssm:SendCommand` is allowed only on the seven
  document ARNs and on `instance/*` and `managed-instance/*` in `123456789012`. Command
  results are readable.
- [ ] T020 [P] [US3] Write failing tests in `tests/unit/identity/test_hosts.py`:
  - FR-007: there are seven documents, one per command group of research R5, all Linux.
  - FR-008: each parameter's pattern or value list rejects every value in the injection
    corpus (`;`, `$(id)`, a backtick, `|`, `&`, `>`, a newline, `..`, `/`, a space, a quote,
    `nginx; rm -rf /`) and accepts `nginx`, `sshd.service` and `getty@tty1`. No command
    uses `{{`, `env`, `printenv`, `set`, `cat`, `systemctl status` or `ps` with `args`.
  - FR-009 and FR-003: under the exact evaluation, the host identity may `SendCommand` each
    catalog document on an instance and on a managed instance. It is denied
    `AWS-RunShellScript`, `AWS-RunPowerShellScript`, any other document, `ssm:StartSession`,
    `ssm:StartAutomationExecution` and `ec2-instance-connect:SendSSHPublicKey`.
  - FR-009: the read-only identity is denied `ssm:SendCommand` on every resource.
  - FR-002: under the robust evaluation, `ssm:SendCommand` is the host identity's only
    write, reported as `1 exception`.
  - FR-013: a copy whose `Disk` document adds `env`, or reads a file given as a parameter,
    or whose pattern is loosened, fails `host-document` or `host-pattern`, naming the
    document and the path within it.
- [ ] T021 [US3] Implement the host identity's wiring, the exception probes and the
  comparison of documents with the reference (parsed equality, with a path to the first
  difference) in `src/opscout/services/identity.py`. T020 passes.

## Phase 6: User Story 4 — clusters show everything except secrets (P2)

**Goal**: the EKS view access policy and a binding to `view`, nothing else.
**Independent test**: the reference passes. The administrator-view policy, an extra role or a
second object fails.

- [ ] T022 [P] [US4] Write `src/opscout/data/identity/eks/access-policy.json` and
  `src/opscout/data/identity/kubernetes/view-binding.yaml` per contracts/documents.md.
- [ ] T023 [P] [US4] Write failing tests in `tests/unit/identity/test_cluster.py`:
  - FR-010: the reference passes. The access scope is `cluster` or `namespace`. The cluster
    capability allows `eks:DescribeCluster` and `eks:ListClusters`.
  - FR-013: each of these fails `cluster`, naming the file:
    - `AmazonEKSAdminViewPolicy`, `AmazonEKSSecretReaderPolicy` or any other policy ARN
    - a `roleRef` other than `ClusterRole` `view`
    - a second object in the manifest, such as a `ClusterRole` that grants `secrets`,
      `pods/exec`, `pods/attach`, `pods/portforward`, `nodes/proxy` or
      `serviceaccounts/token`
    - a `RoleBinding` to `edit`
- [ ] T024 [US4] Implement the cluster proofs in `src/opscout/services/identity.py`. T023
  passes.

## Phase 7: User Story 5 — the person who applies it can confirm it worked (P3)

**Goal**: `opscout identity check | export`, the pre-commit hook, and the instantiation and
live-check documentation.
**Independent test**: export, plant a fault, and check: exit 1 with the finding. The packaged
reference passes with exit 0.

- [ ] T025 [P] [US5] Write failing tests in `tests/unit/identity/test_commands.py`
  (FR-016, contracts/commands.md):
  - `opscout identity check` with no argument prints the packaged reference's summary
    (catalog date, both managed versions, counts) and exits 0
  - on a directory with findings, it prints one line per finding, then `Fail: N findings.`,
    and exits 1
  - a missing directory, or an unparseable file, exits 2 and names the file and line
  - `export DIR` writes only the editable tree, lists the files and the placeholders, and
    exits 0
  - `export` into a directory that already holds any of those files exits 2 and changes
    nothing
  - an exported tree checks clean
  - the check works with the network disabled
- [ ] T026 [US5] Implement `src/opscout/entrypoints/identity.py` (the wiring) and the
  `identity` subcommands in `src/opscout/entrypoints/cli.py`. Keep the import contracts: the
  CLI builds no adapter. T025 passes.
- [ ] T027 [P] [US5] Add `opscout-identity-check` to `.pre-commit-hooks.yaml` per
  contracts/commands.md. Write a failing test in `tests/unit/identity/test_commands.py`
  (FR-016) that the hook's entry is `opscout identity check`, that `pass_filenames` is
  false, and that the file still lists `opscout-config-validate`. Then make it pass.
- [ ] T028 [US5] Write `docs/reference/identity.md` (FR-017, FR-018):
  - **What it is**: the two identities, the capabilities table (generated from
    `capabilities.json` by a test that compares them), and the guardrail groups.
  - **Instantiating**: export, fill the placeholders, and attach. Give one example for an
    IAM role and one for an SSO permission set: Terraform `file()` with
    `aws_iam_policy`/`aws_iam_role_policy_attachment`, and
    `aws_ssoadmin_customer_managed_policy_attachment` with
    `aws_ssoadmin_permissions_boundary_attachment`. Fake values only.
  - **Optional parts**: which parts are optional.
  - **The pre-commit hook.**
  - **Live check**: the probes of research R9, each with its exact command and expected
    outcome.
  - **Known limits**: resource policies that name the session ARN; `ecs:DescribeTasks`
    overrides; host log lines.
  - **The engine never applies anything.**
- [ ] T029 [P] [US5] Write failing tests in `tests/unit/identity/test_docs.py`, then make
  them pass:
  - FR-017: the capabilities table in `docs/reference/identity.md` equals
    `capabilities.json`, and every reference file is named.
  - FR-018: every probe in the live check is one of the cannot-change forms: an `iam
    simulate-principal-policy`, a nonexistent resource, `--dry-run`, or `kubectl auth
    can-i`. Every probe states its expected outcome.

## Phase 8: User Story 6 — tokens for the other systems are read-only too (P3)

- [ ] T030 [US6] Add "Credentials for other systems" to `docs/reference/identity.md`
  (FR-019, research R10), covering observability, code host, tickets and chat. For each,
  give the read scopes to choose, the scopes never to choose, how to confirm the result, and
  the keychain rule. The code-host and chat entries must match `docs/reference/standup.md`
  and `docs/reference/daemon.md`.
- [ ] T031 [P] [US6] Write a failing test in `tests/unit/identity/test_docs.py` (FR-019),
  then make it pass. The section names the four systems. Its Bitbucket scopes equal the
  ones in `docs/reference/standup.md`, and its Slack scopes equal the ones in
  `docs/reference/daemon.md`. No write scope is listed as one to choose.

## Phase 9: Polish and gates

- [ ] T032 Build the wheel and confirm that `opscout/data/identity/` is inside it (research
  R7). Add a test in `tests/unit/identity/test_commands.py` (FR-001) that every reference
  file is reachable through `importlib.resources`.
- [ ] T033 Update `docs/PLAN.md`:
  - §6: replace `deploy/ … reference IAM policies` with `src/opscout/data/identity/`.
  - §7: the readonly-identity paragraph (two identities, the check, the hook); the status
    line says spec 010 is in progress.
  - §9: rule 3's gates. The identity and the host documents exist; the tool allow-lists
    arrive with ops-mcp-server. Add an open item for the live check in a sandbox account
    (FR-021).
  - §9: who applies the identity stays open.
  - Add `docs/reference/identity.md` to the docs index if one lists the references.
- [ ] T034 Write the FR-021 test in `tests/unit/identity/test_traceability.py`: the live
  check is an open item in PLAN.md §9.
- [ ] T035 Update `AGENTS.md`'s rule 3 gate and its repository map:
  - rule 3's gate names `opscout identity check`
  - `src/opscout/data/identity/` is listed
  - `tools/identity_refresh.py` is listed
- [ ] T036 Run `uv run just check` and `uv run just coverage` (100 % on `core` and
  `services`)
- [ ] T037 Converge, then the independent review of the diff in a fresh context. Record the
  findings and fixes in this file.
- [ ] T038 Run the gates again after the review's fixes
- [ ] T039 Check the staged diff for real data (rule 2). Only `123456789012`,
  `example-prod` and `opscout-*` may appear, and the catalog and managed copies must be
  AWS's public data only.
- [ ] T040 Remove the traceability `xfail`. Set the spec's status to Implemented and record
  the effort and measured counts in its Actuals.

## Dependencies

1 → 2 → 3 (US1, MVP) → 4 (US2) → 5 (US3), 6 (US4) → 7 (US5) → 8 (US6) → 9.

- Tests come before their implementation in each phase.
- T003 needs network access once, to the public AWS reference only.
- T013 needs T009 and T010.
- T017 needs T013 and T014.
- T021 needs T017.
- T024 needs T017.
- T026 needs T021 and T024.
- T040 is last.

## Parallel examples

- Phase 2: T005 and T007 together.
- Phase 3: T008, T010, T011 and T012 together; then T009 and T013.
- Phase 4: T014, T015 and T016 together.
- Phases 5 and 6 run side by side: T018, T019, T020, T022 and T023.
- Phase 7: T025, T027 and T029 together.

## Implementation strategy

**MVP**: phases 1 to 3. That gives the catalog, the evaluator, the guardrail and the cap,
proved on the reference and on planted faults, which is the plan's exit criterion. Then
come the declared capabilities and sizes (US2), the hosts (US3) and the clusters (US4).
After that, the command, the hook and the documentation for the person who applies it
(US5, US6). The live check needs an instantiated identity, so it stays an open item
(FR-021).
