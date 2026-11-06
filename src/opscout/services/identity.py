# SPDX-License-Identifier: Apache-2.0
"""Prove the read-only identity's documents (spec 010; research R2-R8).

``prove`` takes a parsed tree, the reference or an instantiated copy, and the package's
records, and returns a report. It passes only when nothing can read a secret or write
(even with ``Allow *`` attached), every declared read is allowed, nothing is granted
outside a declared capability, the host documents equal the reference, the cluster
documents bind only the view level, and every document fits AWS's size limits.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from opscout.core.identity import (
    Analysis,
    CannotProveError,
    Capability,
    Finding,
    FindingKind,
    Identity,
    Policy,
    Records,
    Report,
    Tree,
    parse_policy,
    proves_allowed,
    proves_denied,
    with_allow_all,
)

GUARDRAIL = "aws/guardrail.json"
CAPABILITIES = "aws/readonly/capabilities/"
HOSTS_CAPABILITY = "aws/hosts/capability.json"
HOSTS_BOUNDARY = "aws/hosts/boundary.json"
EKS = "eks/access-policy.json"
KUBERNETES = "kubernetes/view-binding.yaml"
SSM = "ssm/"
READONLY = "read-only identity"
HOSTS = "host identity"

MAX_POLICY = 6_144  # a customer-managed policy, whitespace excluded (research R2)
MAX_INLINE = 10_240  # a permission set's inline policy, whitespace excluded
MAX_ATTACHMENTS = 20  # managed policies per role, IAM's default
EKS_VIEW = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
RBAC = "rbac.authorization.k8s.io"
REGION = "us-east-1"  # any region: the documents use * for it
INSTANCE = "i-0123456789abcdef0"
MANAGED_INSTANCE = "mi-0123456789abcdef0"
SHELL_DOCUMENTS = ("AWS-RunShellScript", "AWS-RunPowerShellScript")
_ACCOUNT = re.compile(r"^arn:aws:[^:]*:[^:]*:(\d{12}):")
_PATTERN_KEYS = frozenset({"allowedPattern", "allowedValues", "interpolationType"})


@dataclass
class _Findings:
    items: list[Finding] = field(default_factory=list)

    def add(self, kind: FindingKind, message: str) -> None:
        self.items.append(Finding(kind, message))


def _parse(tree: Tree, path: str) -> Policy:
    return parse_policy(path, tree.files[path])


def _capability_files(tree: Tree) -> list[str]:
    return sorted(
        path
        for path in tree.files
        if path.startswith(CAPABILITIES) and path.count("/") == CAPABILITIES.count("/")
    )


def readonly_identity(tree: Tree, records: Records) -> Identity:
    """The read-only identity: the view-only grant, the capabilities and the guardrail,
    under the ``ReadOnlyAccess`` cap (research R7)."""
    policies = [records.view_only.policy]
    policies += [_parse(tree, path) for path in _capability_files(tree)]
    if GUARDRAIL in tree.files:
        policies.append(_parse(tree, GUARDRAIL))
    return Identity(READONLY, tuple(policies), records.read_only.policy)


def hosts_identity(tree: Tree, records: Records) -> Identity | None:
    """The host identity, when the tree has one: its capability and the guardrail, under
    its own boundary (research R5)."""
    if HOSTS_CAPABILITY not in tree.files or HOSTS_BOUNDARY not in tree.files:
        return None
    policies = [_parse(tree, HOSTS_CAPABILITY)]
    if GUARDRAIL in tree.files:
        policies.append(_parse(tree, GUARDRAIL))
    return Identity(HOSTS, tuple(policies), _parse(tree, HOSTS_BOUNDARY))


def _capability(records: Records, name: str) -> Capability | None:
    return next((c for c in records.capabilities if c.name == name), None)


def _reference_documents(records: Records) -> list[str]:
    return sorted(path for path in records.reference.files if path.startswith(SSM))


def _expected_paths(records: Records) -> tuple[set[str], set[str]]:
    """Every path a tree may hold, and the paths it must hold."""
    readonly = [c for c in records.capabilities if c.identity == "readonly"]
    allowed = {GUARDRAIL, HOSTS_CAPABILITY, HOSTS_BOUNDARY, EKS, KUBERNETES}
    allowed |= {f"{CAPABILITIES}{c.name}.json" for c in readonly if c.grant == "actions"}
    allowed |= set(_reference_documents(records))
    required = {GUARDRAIL}
    required |= {
        f"{CAPABILITIES}{c.name}.json" for c in readonly if c.grant == "actions" and not c.optional
    }
    return allowed, required


def _prove_layout(tree: Tree, records: Records, findings: _Findings) -> None:
    allowed, required = _expected_paths(records)
    for path in sorted(set(tree.files) - allowed):
        findings.add("layout", f"{path} is not part of the identity")
    for path in sorted(required - set(tree.files)):
        findings.add("layout", f"{path} is missing")
    hosts = [HOSTS_CAPABILITY, HOSTS_BOUNDARY, *_reference_documents(records)]
    present = [path for path in hosts if path in tree.files]
    if present and len(present) != len(hosts):
        missing = ", ".join(path for path in hosts if path not in tree.files)
        findings.add("layout", f"host commands need all of their files; missing {missing}")


def _prove_guardrail(
    identity: Identity, analysis: Analysis, records: Records, findings: _Findings
) -> tuple[int, int]:
    denied = total = 0
    for entry in records.guardrail:
        keys = records.catalog.expand(entry.action)
        if not keys:
            findings.add("unknown-action", f"guardrail entry {entry.action} is not in the catalog")
        for key in sorted(keys):
            total += 1
            scoped = entry.resource != "*"
            reason = (
                analysis.denied_on(key, entry.resource)
                if scoped
                else analysis.denied_everywhere(key)
            )
            if reason is not None:
                denied += 1
            elif scoped:
                findings.add(
                    "secret-allowed",
                    f"{entry.action} on {entry.resource} is not denied on every such resource "
                    f"for the {identity.name}; the guardrail must deny it with a resource that "
                    "covers the whole pattern",
                )
            else:
                findings.add(
                    "secret-allowed",
                    f"{records.catalog.name(key)} is allowed ({analysis.may_allow(key)}) for "
                    f"the {identity.name}; the guardrail must deny it",
                )
    return denied, total


def _prove_writes(
    identity: Identity,
    analysis: Analysis,
    records: Records,
    exceptions: set[str],
    findings: _Findings,
) -> tuple[int, int]:
    denied = total = 0
    for key in records.catalog:
        if not records.catalog.is_write(key):
            continue
        total += 1
        if analysis.denied_everywhere(key) is not None:
            denied += 1
        elif key not in exceptions:
            findings.add(
                "write-allowed",
                f"{records.catalog.name(key)} is allowed with Allow * added "
                f"({analysis.may_allow(key)}) for the {identity.name}; the cap or the "
                "guardrail must deny it",
            )
    return denied, total


def _declared(records: Records, identity: str) -> set[str]:
    return {
        action.lower()
        for capability in records.capabilities
        if capability.identity == identity
        for action in (*capability.actions, *capability.reads)
    }


def _prove_data_plane(identity: Identity, kind: str, records: Records, findings: _Findings) -> None:
    declared = _declared(records, kind)
    analysis = Analysis(identity, records.catalog)
    for key in sorted(analysis.allowed_somewhere()):
        if records.catalog.is_data_plane(key) and key not in declared:
            findings.add(
                "data-allowed",
                f"{records.catalog.name(key)} reads application data ({analysis.may_allow(key)}) "
                f"for the {identity.name}; declare it in a capability or deny it",
            )


def _prove_reads(
    identity: Identity, capabilities: Iterable[Capability], findings: _Findings
) -> tuple[int, int]:
    allowed = total = 0
    for capability in capabilities:
        for action in capability.reads:
            total += 1
            ok, reason = proves_allowed(identity, action, "*")
            allowed += ok
            if not ok:
                findings.add(
                    "read-missing",
                    f"{action} (capability {capability.name}) is denied ({reason})",
                )
    return allowed, total


def _prove_declared(
    policy: Policy, capability: Capability | None, records: Records, findings: _Findings
) -> None:
    if capability is None:
        return
    declared = {action.lower() for action in capability.actions}
    for statement in policy.statements:
        if statement.effect != "Allow":
            continue
        if statement.not_action or any("*" in a or "?" in a for a in statement.actions):
            findings.add(
                "undeclared-grant",
                f"{statement.ref} uses a wildcard or NotAction; capability documents list "
                "exact actions",
            )
            continue
        for action in statement.actions:
            if records.catalog.name(action) is None:
                findings.add("unknown-action", f"{action} in {statement.ref} is not in the catalog")
            elif action.lower() not in declared:
                findings.add(
                    "undeclared-grant", f"{action} in {statement.ref} belongs to no capability"
                )


def _prove_guardrail_document(policy: Policy, records: Records, findings: _Findings) -> None:
    for statement in policy.statements:
        if statement.effect == "Allow":
            findings.add("undeclared-grant", f"{statement.ref} allows; the guardrail only denies")
            continue
        for action in statement.actions:
            if "*" not in action and "?" not in action and records.catalog.name(action) is None:
                findings.add("unknown-action", f"{action} in {statement.ref} is not in the catalog")


def _size(document: object) -> int:
    return len(re.sub(r"\s", "", json.dumps(document)))


def _prove_sizes(tree: Tree, findings: _Findings) -> str:
    sizes = {
        path: _size(document)
        for path, document in tree.files.items()
        if path.startswith("aws/") and path.endswith(".json")
    }
    for path, size in sorted(sizes.items()):
        if size > MAX_POLICY:
            findings.add("too-large", f"{path} has {size:,} characters (limit {MAX_POLICY:,})")
    inline = sum(
        size for path, size in sizes.items() if path == GUARDRAIL or path.startswith(CAPABILITIES)
    )
    if inline > MAX_INLINE:
        findings.add(
            "too-large",
            f"the guardrail and the capabilities have {inline:,} characters together "
            f"(limit {MAX_INLINE:,} for one inline policy)",
        )
    attachments = 2 + len(_capability_files(tree))  # the view-only grant and the guardrail
    if attachments > MAX_ATTACHMENTS:
        findings.add(
            "too-large", f"the {READONLY} has {attachments} policies (limit {MAX_ATTACHMENTS})"
        )
    if not sizes:
        return "Sizes: no AWS documents"
    largest = max(sizes, key=lambda path: sizes[path])
    return (
        f"Sizes: largest {sizes[largest]:,}/{MAX_POLICY:,} ({largest}); "
        f"inline total {inline:,}/{MAX_INLINE:,}"
    )


def _accounts(value: object) -> Iterable[str]:
    if isinstance(value, str):
        match = _ACCOUNT.match(value)
        if match:
            yield match.group(1)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _accounts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _accounts(item)


def _prove_placeholders(tree: Tree, findings: _Findings) -> str:
    where: dict[str, list[str]] = {}
    for path, document in sorted(tree.files.items()):
        if path.startswith(("aws/", "eks/")):
            for account in set(_accounts(document)):
                where.setdefault(account, []).append(path)
    if len(where) > 1:
        names = "; ".join(", ".join(paths) for paths in where.values())
        findings.add(
            "placeholder",
            f"the documents name {len(where)} different accounts ({names}); "
            "one identity is one account",
        )
    return next(iter(where), "123456789012")


def _difference(expected: Any, actual: Any, path: str = "") -> str | None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual), key=str):
            if key not in expected or key not in actual:
                return f"{path}.{key}".lstrip(".")
            found = _difference(expected[key], actual[key], f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for index in range(max(len(expected), len(actual))):
            if index >= len(expected) or index >= len(actual):
                return f"{path}[{index}]"
            found = _difference(expected[index], actual[index], f"{path}[{index}]")
            if found is not None:
                return found
        return None
    same = type(expected) is type(actual) and expected == actual
    return None if same else (path.lstrip(".") or "the document")


def _prove_host_documents(tree: Tree, records: Records, findings: _Findings) -> tuple[int, int]:
    documents = [path for path in _reference_documents(records) if path in tree.files]
    matching = 0
    for path in documents:
        actual = tree.files[path]
        expected = records.reference.files[path]
        where = _difference(expected, actual)
        if where is None:
            matching += 1
            continue
        parts = set(re.split(r"[.\[\]]", where))
        kind: FindingKind = "host-pattern" if parts & _PATTERN_KEYS else "host-document"
        findings.add(kind, f"{path} differs from the reference at {where.removeprefix('[0].')}")
    return matching, len(documents)


def _prove_host_exceptions(
    identity: Identity, account: str, documents: list[str], findings: _Findings
) -> int:
    instance = f"arn:aws:ec2:{REGION}:{account}:instance/{INSTANCE}"
    managed = f"arn:aws:ssm:{REGION}:{account}:managed-instance/{MANAGED_INSTANCE}"
    sendable = 0
    for path in documents:
        name = path.removeprefix(SSM).rsplit(".", 1)[0]
        document = f"arn:aws:ssm:{REGION}:{account}:document/{name}"
        for target in (instance, managed):
            ok, reason = proves_allowed(identity, "ssm:SendCommand", document, target)
            if not ok:
                findings.add(
                    "read-missing", f"ssm:SendCommand of {name} on {target} is denied ({reason})"
                )
        sendable += 1
    robust = with_allow_all(identity)
    others = [f"arn:aws:ssm:{REGION}::document/{name}" for name in SHELL_DOCUMENTS]
    others += [
        f"arn:aws:ssm:{REGION}:{account}:document/example-other",
        f"arn:aws:ssm:{REGION}:{account}:document/opscout-ReadOnly-Unlisted",
    ]
    for document in others:
        ok, reason = proves_denied(robust, "ssm:SendCommand", document, instance)
        if not ok:
            findings.add(
                "exception-too-wide",
                f"ssm:SendCommand allowed on {document} ({reason}) for the {identity.name}",
            )
    return sendable


def _prove_send_command_resources(
    policies: Iterable[Policy],
    account: str,
    documents: list[str],
    records: Records,
    findings: _Findings,
) -> None:
    """Every resource a host document allows ``ssm:SendCommand`` on must be a catalog
    document or an instance of this account, named exactly (research R5)."""
    names = "|".join(re.escape(path.removeprefix(SSM).rsplit(".", 1)[0]) for path in documents)
    region = r"(\*|[a-z0-9-]+)"
    allowed = re.compile(
        rf"^(arn:aws:ssm:{region}:{account}:document/({names or '(?!)'})"
        rf"|arn:aws:ec2:{region}:{account}:instance/\*"
        rf"|arn:aws:ssm:{region}:{account}:managed-instance/\*)$"
    )
    for policy in policies:
        for statement in policy.statements:
            if statement.effect != "Allow":
                continue
            if "ssm:sendcommand" not in records.catalog.covered(statement):
                continue
            if statement.not_resource:
                findings.add(
                    "exception-too-wide",
                    f"{statement.ref} allows ssm:SendCommand through NotResource; name the "
                    "catalog documents and the instances",
                )
                continue
            for resource in statement.resources:
                if not allowed.match(resource):
                    findings.add(
                        "exception-too-wide",
                        f"ssm:SendCommand allowed on {resource} ({statement.ref}); only the "
                        f"catalog documents and the instances of account {account} may be named",
                    )


def _prove_cluster(tree: Tree, findings: _Findings) -> str:
    parts = []
    if EKS in tree.files:
        entry = tree.files[EKS]
        scope = entry.get("accessScope", {}) if isinstance(entry, Mapping) else {}
        if not isinstance(entry, Mapping) or entry.get("policyArn") != EKS_VIEW:
            policy = entry.get("policyArn") if isinstance(entry, Mapping) else None
            findings.add(
                "cluster",
                f"{EKS} uses {policy}; only AmazonEKSViewPolicy is allowed",
            )
        elif not isinstance(scope, Mapping) or scope.get("type") not in ("cluster", "namespace"):
            findings.add("cluster", f"{EKS} needs an accessScope of type cluster or namespace")
        parts.append("EKS view policy")
    if KUBERNETES in tree.files:
        documents = [d for d in tree.files[KUBERNETES] if d is not None]
        expected_ref = {"kind": "ClusterRole", "name": "view", "apiGroup": RBAC}
        if len(documents) != 1:
            findings.add("cluster", f"{KUBERNETES} must hold one ClusterRoleBinding only")
        else:
            binding = documents[0]
            subjects = binding.get("subjects") if isinstance(binding, Mapping) else None
            if (
                not isinstance(binding, Mapping)
                or binding.get("kind") != "ClusterRoleBinding"
                or binding.get("apiVersion") != f"{RBAC}/v1"
            ):
                findings.add("cluster", f"{KUBERNETES} must hold one ClusterRoleBinding only")
            elif binding.get("roleRef") != expected_ref:
                findings.add(
                    "cluster",
                    f"{KUBERNETES} must bind the ClusterRole view; it binds "
                    f"{binding.get('roleRef')}",
                )
            elif (
                not isinstance(subjects, list)
                or not subjects
                or any(
                    not isinstance(s, Mapping) or s.get("kind") not in ("Group", "User")
                    for s in subjects
                )
            ):
                findings.add("cluster", f"{KUBERNETES} may bind groups or users only")
            elif any(str(s.get("name", "")).startswith("system:") for s in subjects):
                findings.add(
                    "cluster",
                    f"{KUBERNETES} binds a system: group or user, such as every "
                    "unauthenticated caller; bind the identity's own group",
                )
        parts.append("view binding only")
    return f"Cluster: {'; '.join(parts)}" if parts else "Cluster: not part of this tree"


def prove(tree: Tree, records: Records) -> Report:
    """Prove a tree against the package's records (FR-011 to FR-013)."""
    findings = _Findings()
    catalog = records.catalog
    summary = [
        f"Catalog: AWS service reference, fetched {catalog.fetched} "
        f"({len(catalog.services)} services, {len(catalog):,} actions)",
        f"Managed: ViewOnlyAccess {records.view_only.version}, ReadOnlyAccess "
        f"{records.read_only.version} (recorded {records.read_only.fetched})",
    ]
    _prove_layout(tree, records, findings)
    try:
        readonly = readonly_identity(tree, records)
        hosts = hosts_identity(tree, records)
    except CannotProveError as error:
        findings.add("cannot-prove", f"{error.ref}: {error.message}")
        return Report(tuple(summary), tuple(findings.items))

    account = _prove_placeholders(tree, findings)
    documents = [path for path in _reference_documents(records) if path in tree.files]

    robust = Analysis(with_allow_all(readonly), catalog)
    secrets = _prove_guardrail(readonly, robust, records, findings)
    writes = _prove_writes(readonly, robust, records, set(), findings)
    present = {
        path.removeprefix(CAPABILITIES).removesuffix(".json") for path in _capability_files(tree)
    }
    readonly_capabilities = [
        c
        for c in records.capabilities
        if c.identity == "readonly" and (c.grant == "managed" or c.name in present)
    ]
    reads = _prove_reads(readonly, readonly_capabilities, findings)
    _prove_data_plane(readonly, "readonly", records, findings)
    for path in _capability_files(tree):
        name = path.removeprefix(CAPABILITIES).removesuffix(".json")
        _prove_declared(_parse(tree, path), _capability(records, name), records, findings)
    if GUARDRAIL in tree.files:
        _prove_guardrail_document(_parse(tree, GUARDRAIL), records, findings)
    summary.append(
        f"Read-only identity: secret reads {secrets[0]:,}/{secrets[1]:,} denied; writes "
        f"{writes[0]:,}/{writes[1]:,} denied; reads {reads[0]:,}/{reads[1]:,} allowed"
    )

    if hosts is None:
        summary.append("Host identity: not part of this tree")
    else:
        robust_hosts = Analysis(with_allow_all(hosts), catalog)
        _prove_guardrail(hosts, robust_hosts, records, findings)
        host_writes = _prove_writes(hosts, robust_hosts, records, {"ssm:sendcommand"}, findings)
        hosts_capability = [c for c in records.capabilities if c.identity == "hosts"]
        host_reads = _prove_reads(hosts, hosts_capability, findings)
        _prove_data_plane(hosts, "hosts", records, findings)
        for path in (HOSTS_CAPABILITY, HOSTS_BOUNDARY):
            _prove_declared(_parse(tree, path), _capability(records, "hosts"), records, findings)
        sendable = _prove_host_exceptions(hosts, account, documents, findings)
        _prove_send_command_resources(
            (_parse(tree, HOSTS_CAPABILITY), _parse(tree, HOSTS_BOUNDARY)),
            account,
            documents,
            records,
            findings,
        )
        exceptions = host_writes[1] - host_writes[0]
        summary.append(
            f"Host identity: writes {host_writes[0]:,}/{host_writes[1]:,} denied, "
            f"{exceptions} exception (ssm:SendCommand on {sendable} documents); reads "
            f"{host_reads[0]:,}/{host_reads[1]:,} allowed"
        )

    matching, total = _prove_host_documents(tree, records, findings)
    summary.append(
        f"Host documents: {matching}/{total} match the reference"
        if total
        else "Host documents: not part of this tree"
    )
    summary.append(_prove_cluster(tree, findings))
    summary.append(_prove_sizes(tree, findings))
    return Report(tuple(summary), tuple(findings.items))
