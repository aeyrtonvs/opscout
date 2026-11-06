# Contract: reference documents

All values are placeholders (data-model.md). Each excerpt shows a document's shape. The
final action lists are fixed in implementation and proved by the check.

## `aws/guardrail.json` (excerpt)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenySecretValues",
      "Effect": "Deny",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:BatchGetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
        "ssm:GetParameterHistory",
        "kms:Decrypt",
        "kms:GenerateDataKey*",
        "kms:ReEncrypt*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyApiKeyValues",
      "Effect": "Deny",
      "Action": "apigateway:GET",
      "Resource": [
        "arn:aws:apigateway:*::/apikeys",
        "arn:aws:apigateway:*::/apikeys/*"
      ]
    },
    {
      "Sid": "DenyOtherCommandDocuments",
      "Effect": "Deny",
      "Action": "ssm:SendCommand",
      "NotResource": [
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-*",
        "arn:aws:ec2:*:123456789012:instance/*",
        "arn:aws:ssm:*:123456789012:managed-instance/*"
      ]
    }
  ]
}
```

The last statement repeats the host boundary's limit, so that the guardrail alone also stops
a shell document. The other groups (credentials, plaintext-secret reads, data plane,
sessions) follow the same form.

## `aws/readonly/capabilities/logs.json` (excerpt)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
        "logs:DescribeQueries"
      ],
      "Resource": "*"
    }
  ]
}
```

## `aws/hosts/capability.json` (also `boundary.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SendCatalogDocuments",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-Uptime",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-Memory",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-Disk",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-TopProcesses",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-ServiceState",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-ServiceLog",
        "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-ListeningPorts",
        "arn:aws:ec2:*:123456789012:instance/*",
        "arn:aws:ssm:*:123456789012:managed-instance/*"
      ]
    },
    {
      "Sid": "ReadCommandResults",
      "Effect": "Allow",
      "Action": [
        "ssm:GetCommandInvocation",
        "ssm:ListCommandInvocations",
        "ssm:ListCommands",
        "ssm:DescribeInstanceInformation"
      ],
      "Resource": "*"
    }
  ]
}
```

## `ssm/opscout-ReadOnly-ServiceLog.yaml`

```yaml
schemaVersion: "2.2"
description: "opscout: the last lines of one systemd unit's journal (read-only)."
parameters:
  ServiceName:
    type: String
    description: A systemd unit name.
    allowedPattern: "^[A-Za-z0-9@._-]{1,64}$"
    interpolationType: ENV_VAR
  Lines:
    type: String
    description: How many lines.
    allowedValues: ["50", "100", "200"]
    default: "50"
    interpolationType: ENV_VAR
mainSteps:
  - action: aws:runShellScript
    name: serviceLog
    precondition:
      StringEquals: [platformType, Linux]
    inputs:
      runCommand:
        - journalctl --unit="$SSM_ServiceName" --lines="$SSM_Lines" --no-pager --output=short-iso
```

## `eks/access-policy.json`

```json
{
  "clusterName": "example-prod",
  "principalArn": "arn:aws:iam::123456789012:role/opscout-readonly",
  "policyArn": "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy",
  "accessScope": { "type": "cluster" }
}
```

## `kubernetes/view-binding.yaml`

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: opscout-readonly-view
subjects:
  - kind: Group
    name: opscout:readonly
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```
