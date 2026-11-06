# SPDX-License-Identifier: Apache-2.0
"""Clusters show everything except secrets (spec 010, FR-010, FR-013; research R6)."""

import copy
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Records, Report, Tree, proves_allowed
from opscout.services.identity import prove, readonly_identity

EKS = "eks/access-policy.json"
BINDING = "kubernetes/view-binding.yaml"
RBAC = "rbac.authorization.k8s.io"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _files(records: Records) -> dict[str, Any]:
    return copy.deepcopy(dict(records.reference.files))


def _messages(report: Report) -> str:
    return "\n".join(f.message for f in report.findings if f.kind == "cluster")


@spec("FR-010")
def test_the_reference_binds_only_the_view_level(records: Records) -> None:
    report = prove(records.reference, records)

    assert report.passed, report.findings
    assert "Cluster: EKS view policy; view binding only" in report.summary
    entry = records.reference.files[EKS]
    assert entry["policyArn"].endswith("/AmazonEKSViewPolicy")
    assert entry["accessScope"] == {"type": "cluster"}


@spec("FR-010")
def test_a_namespace_scope_is_allowed(records: Records) -> None:
    files = _files(records)
    files[EKS]["accessScope"] = {"type": "namespace", "namespaces": ["example-prod"]}

    assert prove(Tree(files), records).passed


@spec("FR-010")
def test_the_cluster_capability_reaches_eks(records: Records) -> None:
    identity = readonly_identity(records.reference, records)

    for action in ("eks:DescribeCluster", "eks:ListClusters"):
        assert proves_allowed(identity, action, "*") == (True, None)


@spec("FR-013")
@pytest.mark.parametrize(
    "policy", ["AmazonEKSAdminViewPolicy", "AmazonEKSSecretReaderPolicy", "AmazonEKSEditPolicy"]
)
def test_another_access_policy_is_refused(records: Records, policy: str) -> None:
    files = _files(records)
    files[EKS]["policyArn"] = f"arn:aws:eks::aws:cluster-access-policy/{policy}"

    assert f"uses arn:aws:eks::aws:cluster-access-policy/{policy}" in _messages(
        prove(Tree(files), records)
    )


@spec("FR-013")
def test_a_missing_scope_is_refused(records: Records) -> None:
    files = _files(records)
    del files[EKS]["accessScope"]

    assert "accessScope" in _messages(prove(Tree(files), records))


@spec("FR-013")
def test_another_role_is_refused(records: Records) -> None:
    files = _files(records)
    files[BINDING][0]["roleRef"]["name"] = "edit"

    assert "must bind the ClusterRole view" in _messages(prove(Tree(files), records))


@spec("FR-013")
@pytest.mark.parametrize(
    "resource",
    [
        "secrets",
        "pods/exec",
        "pods/attach",
        "pods/portforward",
        "nodes/proxy",
        "serviceaccounts/token",
    ],
)
def test_a_second_object_granting_more_is_refused(records: Records, resource: str) -> None:
    files = _files(records)
    files[BINDING].append(
        {
            "apiVersion": f"{RBAC}/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "extra", "labels": {f"{RBAC}/aggregate-to-view": "true"}},
            "rules": [{"apiGroups": [""], "resources": [resource], "verbs": ["get", "create"]}],
        }
    )

    assert "one ClusterRoleBinding only" in _messages(prove(Tree(files), records))


@spec("FR-013")
def test_a_role_binding_to_edit_is_refused(records: Records) -> None:
    files = _files(records)
    files[BINDING] = [
        {
            "apiVersion": f"{RBAC}/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "x", "namespace": "example"},
            "subjects": [{"kind": "Group", "name": "opscout:readonly", "apiGroup": RBAC}],
            "roleRef": {"kind": "ClusterRole", "name": "edit", "apiGroup": RBAC},
        }
    ]

    assert "one ClusterRoleBinding only" in _messages(prove(Tree(files), records))


@spec("FR-013")
def test_a_service_account_subject_is_refused(records: Records) -> None:
    files = _files(records)
    files[BINDING][0]["subjects"] = [{"kind": "ServiceAccount", "name": "x", "namespace": "y"}]

    assert "groups or users only" in _messages(prove(Tree(files), records))
