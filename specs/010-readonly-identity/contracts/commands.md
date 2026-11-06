# Contract: commands

## `opscout identity check [DIR]`

Checks the tree in `DIR`, or the packaged reference when `DIR` is omitted. It works offline
and reads only. The output on success:

```text
Catalog: AWS service reference, fetched 2026-11-05 (457 services, 20,113 actions)
Managed: ViewOnlyAccess v48, ReadOnlyAccess v131 (recorded 2026-11-05)
Read-only identity: secret reads 58/58 denied; writes 14,902/14,902 denied; reads 41/41 allowed
Host identity: writes 14,901/14,902 denied, 1 exception (ssm:SendCommand on 7 documents); reads 5/5 allowed
Host documents: 7/7 match the reference
Cluster: EKS view policy; view binding only
Sizes: largest 2,310/6,144 (aws/guardrail.json); inline total 5,880/10,240
Pass.
```

On failure, each finding is a line, then `Fail: N findings.`:

```text
secret-allowed: secretsmanager:GetSecretValue is allowed (aws/readonly/capabilities/logs.json#2); the guardrail must deny it
write-allowed: ec2:CreateTags is allowed with Allow * added; the boundary or the guardrail must deny it
exception-too-wide: ssm:SendCommand allowed on arn:aws:ssm:*:123456789012:document/AWS-RunShellScript (aws/hosts/capability.json#1)
read-missing: cloudwatch:GetMetricData (capability metrics) is denied (aws/guardrail.json#4)
undeclared-grant: ec2:DescribeVolumes in aws/readonly/capabilities/cost.json#1 belongs to no capability
unknown-action: logs:GetLogEvent in aws/readonly/capabilities/logs.json#1 is not in the catalog
cannot-prove: aws/guardrail.json#3 uses Principal
too-large: aws/guardrail.json has 6,410 characters (limit 6,144)
host-document: ssm/opscout-ReadOnly-Disk.yaml differs from the reference at mainSteps[0].inputs.runCommand[1]
host-pattern: ssm/opscout-ReadOnly-ServiceLog.yaml parameter ServiceName pattern differs from the reference
cluster: eks/access-policy.json uses AmazonEKSAdminViewPolicy; only AmazonEKSViewPolicy is allowed
layout: aws/readonly/extra.json is not part of the identity
placeholder: aws/hosts/capability.json and eks/access-policy.json name different accounts (one identity is one account)
```

The numbers above illustrate the format and are not measured.

| Exit | Meaning |
|---|---|
| 0 | pass |
| 1 | one or more findings |
| 2 | a usage error, or a directory that does not exist or cannot be parsed (the message names the file and the line) |

## `opscout identity export DIR`

Writes the editable tree (data-model.md) into `DIR`, then prints the files written and the
placeholders to fill. It refuses a `DIR` that already holds any of those files (exit 2) and
overwrites nothing. Exit 0 when written.

## Pre-commit hook

In `.pre-commit-hooks.yaml`:

```yaml
- id: opscout-identity-check
  name: opscout read-only identity
  description: Prove the read-only identity's documents deny secret reads and writes.
  entry: opscout identity check
  language: python
  pass_filenames: false
  files: ''
```

An infrastructure repository uses it with its tree's path:

```yaml
- repo: https://github.com/aeyrtonvs/opscout
  rev: <commit>
  hooks:
    - id: opscout-identity-check
      args: [opscout-identity]
      files: ^opscout-identity/
```

## Development: `uv run python -m tools.identity_refresh`

Downloads the service reference index and every service file, and the two managed policies
from the AWS Managed Policy Reference. Rewrites `catalog.json` and `managed/*.json`, then
prints the actions that were added, removed or reclassified, and the managed-policy
versions. Then the maintainer runs the check, reviews the diff and commits it (FR-015). The
tool is not shipped.
