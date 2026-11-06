# Data model: Read-only identity

## Package-owned records (`src/opscout/data/identity/`, never read from a checked tree)

### Action catalog (`catalog.json`, R1)

| Field | Type | Rule |
|---|---|---|
| `source` | URL | `https://servicereference.us-east-1.amazonaws.com/` |
| `fetched` | date | the refresh date; printed by the check |
| `services.<prefix>.version` | string | the service file's `Version` |
| `services.<prefix>.actions.<Name>` | string | flags from `w p t l d`, sorted; `""` is read |

Lookup is case-insensitive on prefix and name. An action is a **write** when its flags hold
`w`, `p` or `t`.

### Managed-policy copies (`managed/ViewOnlyAccess.json`, `managed/ReadOnlyAccess.json`, R2)

`{ "arn", "version", "fetched", "document" }`. `document` is the policy JSON exactly as AWS
publishes it.

### Capability declarations (`capabilities.json`, FR-004)

| Field | Type | Rule |
|---|---|---|
| `name` | slug | one of `configuration`, `secret-metadata`, `metrics`, `logs`, `changes`, `cost`, `cluster`, `hosts` |
| `purpose` | text | one sentence |
| `agents` | list | of `alert-triage`, `cost-triage`, `ask` |
| `identity` | enum | `readonly` or `hosts` |
| `optional` | bool | `true` for `cluster` and `hosts` |
| `grant` | enum | `managed` (`configuration` only, by its ARN) or `actions` |
| `actions` | list | exact `service:Action` names, each in the catalog; no wildcards |
| `reads` | list | the actions the check proves allowed (`grant: managed` lists a sample) |

### Guardrail list (`guardrail-actions.json`, R4)

Groups (`secret-values`, `credentials`, `plaintext-secrets`, `data-plane`, `sessions`,
`capped-writes`), each
holding entries `{ "action": "<pattern>", "resource": "<arn pattern>" | "*", "why": text }`.
Each entry must be denied under the robust evaluation (R3). An entry with a resource is
proved with an exact probe on that resource.

## Editable tree (exported, instantiated, checked)

| Path | Kind | Required |
|---|---|---|
| `aws/guardrail.json` | IAM policy | yes |
| `aws/readonly/capabilities/<name>.json` | IAM policy, one per `actions` capability of `readonly` | `secret-metadata`, `metrics`, `logs`, `changes` and `cost` yes; `cluster` optional |
| `aws/hosts/capability.json`, `aws/hosts/boundary.json` | IAM policies | optional, as a pair, with `ssm/` |
| `ssm/opscout-ReadOnly-<Name>.yaml` | SSM Command document, schema 2.2 | all seven or none |
| `eks/access-policy.json` | `associate-access-policy` input | optional, with `kubernetes/` or alone |
| `kubernetes/view-binding.yaml` | one `ClusterRoleBinding` | optional |

Any other file is an error, except dotfiles and a `README.md`, which are skipped, so that the
directory can sit in an infrastructure repository. Attachments follow from the layout (R7):

- **The read-only identity** = the `ViewOnlyAccess` copy, plus `capabilities/*`, plus the
  guardrail; its boundary is the `ReadOnlyAccess` copy.
- **The host identity** = `hosts/capability.json` plus the guardrail; its boundary is
  `hosts/boundary.json`.

### IAM policy (parsed)

- **`Version`**: `2012-10-17`.
- **`Statement`**: a list, or a single statement. Each statement has:
  - `Sid` (optional)
  - `Effect`: `Allow` or `Deny`
  - exactly one of `Action` or `NotAction`, a string or a list
  - exactly one of `Resource` or `NotResource`
  - `Condition` (optional; kept, and treated conservatively, R3)
- **Anything else fails as "cannot prove"**: `Principal`, `NotPrincipal`, another `Version`,
  or an unknown key.

### Placeholders

| Placeholder | Where | Rule in a checked tree |
|---|---|---|
| `123456789012` | ARNs in `aws/hosts/*`, `eks/` | any 12 digits, the same everywhere |
| `example-prod` | `eks/` cluster | any cluster name |
| `opscout-readonly`, `opscout:readonly` | `eks/` principal, `kubernetes/` subject | any role and group name |

## Evaluation types (core)

- **Request**: `(action, resource)`. SendCommand is two requests, one for the document and
  one for the instance, and both must be allowed.
- **Decision**: `allow`, `implicit-deny`, `explicit-deny (statement ref)`.
- **Statement ref**: `<file>#<index or Sid>`.
- **Finding**: `{ kind, message }`. The message names the subject (an action, file or
  document) and, when one applies, the statement ref. The kinds are:
  - `secret-allowed`
  - `write-allowed`
  - `data-allowed`
  - `exception-too-wide`
  - `read-missing`
  - `undeclared-grant`
  - `unknown-action`
  - `cannot-prove`
  - `too-large`
  - `host-document`
  - `host-pattern`
  - `cluster`
  - `layout`
  - `placeholder`
- **Report**: the catalog date, the counts (secret entries denied/total; writes denied, or
  covered by an exception, out of the total; declared reads allowed/total; host documents;
  cluster documents) and the findings. It passes when there are no findings.

## State

None. Every run reads the package records and the tree, and prints a report.
