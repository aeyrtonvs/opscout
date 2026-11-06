# SPDX-License-Identifier: Apache-2.0
"""Capabilities: declared, allowed, nothing beyond them (spec 010; FR-001, 004, 006, 012)."""

import copy
import json
import re
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import (
    Records,
    Report,
    Tree,
    proves_allowed,
    proves_denied,
    with_allow_all,
)
from opscout.services.identity import prove, readonly_identity

AGENTS = {"alert-triage", "cost-triage", "ask"}
CAPABILITIES = "aws/readonly/capabilities/"
SECRET = "arn:aws:secretsmanager:us-east-1:123456789012:secret:example-prod-db-AbCdEf"  # noqa: S105  (an ARN, not a value)
PARAMETER = "arn:aws:ssm:us-east-1:123456789012:parameter/example-prod/db/password"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _files(records: Records) -> dict[str, Any]:
    return copy.deepcopy(dict(records.reference.files))


def _kinds(report: Report) -> set[str]:
    return {finding.kind for finding in report.findings}


def _messages(report: Report, kind: str) -> str:
    return "\n".join(f.message for f in report.findings if f.kind == kind)


@spec("FR-004")
def test_every_capability_states_its_purpose_agents_and_actions(records: Records) -> None:
    names = [c.name for c in records.capabilities]
    assert names == [
        "configuration",
        "secret-metadata",
        "metrics",
        "logs",
        "changes",
        "inventory",
        "cost",
        "cluster",
        "hosts",
    ]
    for capability in records.capabilities:
        assert capability.purpose.endswith(".")
        assert capability.agents
        assert set(capability.agents) <= AGENTS
        assert capability.reads
        if capability.grant == "managed":
            assert capability.name == "configuration"
            assert not capability.actions
        else:
            assert capability.actions
            assert all("*" not in action for action in capability.actions)
    optional = {c.name for c in records.capabilities if c.optional}
    assert optional == {"cluster", "hosts"}


@spec("FR-004")
def test_the_tool_server_reads_are_declared(records: Records) -> None:
    """Spec 011 (research R4) added three reads its tools need, each to a capability."""
    by_name = {c.name: c for c in records.capabilities}
    assert "cloudformation:DescribeStackEvents" in by_name["changes"].actions
    inventory = by_name["inventory"]
    assert inventory.actions == ("tag:GetResources", "cloudformation:DescribeStackResources")
    assert set(inventory.agents) == {"alert-triage", "ask"}
    assert (inventory.identity, inventory.optional, inventory.grant) == (
        "readonly",
        False,
        "actions",
    )
    report = prove(records.reference, records)
    assert report.passed, report.findings
    assert "reads 45/45 allowed" in "\n".join(report.summary)
    identity = readonly_identity(records.reference, records)
    assert len(identity.policies) == 9
    for action in inventory.actions:
        assert proves_allowed(identity, action, "*") == (True, None)


@spec("FR-004")
def test_secret_metadata_is_readable_while_the_value_stays_denied(records: Records) -> None:
    identity = readonly_identity(records.reference, records)
    robust = with_allow_all(identity)

    assert proves_allowed(identity, "secretsmanager:DescribeSecret", SECRET)[0]
    assert proves_allowed(identity, "secretsmanager:ListSecrets", "*")[0]
    assert proves_allowed(identity, "ssm:DescribeParameters", "*")[0]
    assert proves_denied(robust, "secretsmanager:GetSecretValue", SECRET)[0]
    assert proves_denied(robust, "ssm:GetParameter", PARAMETER)[0]


@spec("FR-004")
def test_a_denied_read_names_its_capability(records: Records) -> None:
    files = _files(records)
    files["aws/guardrail.json"]["Statement"].append(
        {"Effect": "Deny", "Action": "cloudwatch:GetMetricData", "Resource": "*"}
    )

    report = prove(Tree(files), records)

    assert "cloudwatch:GetMetricData (capability metrics) is denied" in _messages(
        report, "read-missing"
    )


@spec("FR-012")
def test_an_undeclared_action_is_named(records: Records) -> None:
    files = _files(records)
    files[f"{CAPABILITIES}cost.json"]["Statement"][0]["Action"].append("ec2:DescribeVolumes")

    report = prove(Tree(files), records)

    assert "ec2:DescribeVolumes in aws/readonly/capabilities/cost.json#Cost" in _messages(
        report, "undeclared-grant"
    )


@spec("FR-012")
def test_an_unknown_action_is_named(records: Records) -> None:
    files = _files(records)
    files[f"{CAPABILITIES}logs.json"]["Statement"][0]["Action"].append("logs:GetLogEvent")

    report = prove(Tree(files), records)

    assert "logs:GetLogEvent in aws/readonly/capabilities/logs.json#Logs is not in the catalog" in (
        _messages(report, "unknown-action")
    )


@spec("FR-012")
def test_a_wildcard_in_a_capability_is_refused(records: Records) -> None:
    files = _files(records)
    files[f"{CAPABILITIES}logs.json"]["Statement"][0]["Action"] = ["logs:Get*"]

    report = prove(Tree(files), records)

    assert "uses a wildcard" in _messages(report, "undeclared-grant")


@spec("FR-012")
def test_an_allow_in_the_guardrail_is_refused(records: Records) -> None:
    files = _files(records)
    files["aws/guardrail.json"]["Statement"].append(
        {"Effect": "Allow", "Action": "ec2:DescribeVpcs", "Resource": "*"}
    )

    report = prove(Tree(files), records)

    assert "the guardrail only denies" in _messages(report, "undeclared-grant")


@spec("FR-006")
@pytest.mark.parametrize(
    "removed",
    [
        ("aws/readonly/capabilities/cluster.json",),
        ("aws/hosts/", "ssm/"),
        ("eks/", "kubernetes/"),
        ("aws/readonly/capabilities/cluster.json", "aws/hosts/", "ssm/", "eks/", "kubernetes/"),
    ],
)
def test_leaving_out_an_optional_part_still_passes(
    records: Records, removed: tuple[str, ...]
) -> None:
    files = {k: v for k, v in _files(records).items() if not k.startswith(removed)}

    report = prove(Tree(files), records)

    assert report.passed, report.findings


@spec("FR-006")
def test_leaving_out_a_required_capability_or_adding_a_file_fails_layout(
    records: Records,
) -> None:
    files = _files(records)
    del files[f"{CAPABILITIES}metrics.json"]
    files["aws/readonly/notes.txt"] = None

    report = prove(Tree(files), records)

    assert _messages(report, "layout") == (
        "aws/readonly/notes.txt is not part of the identity\n"
        "aws/readonly/capabilities/metrics.json is missing"
    )


@spec("FR-006")
def test_host_commands_need_all_of_their_files(records: Records) -> None:
    files = _files(records)
    del files["ssm/opscout-ReadOnly-Disk.yaml"]

    report = prove(Tree(files), records)

    assert "host commands need all of their files" in _messages(report, "layout")


@spec("FR-001")
def test_the_reference_uses_only_reserved_values(records: Records) -> None:
    text = json.dumps(dict(records.reference.files))

    assert set(re.findall(r"\b\d{12}\b", text)) <= {"123456789012"}
    assert set(re.findall(r'"clusterName": "([^"]+)"', text)) <= {"example-prod"}
    roles = set(re.findall(r":role/([A-Za-z0-9+=,.@_-]+)", text))
    assert roles <= {"opscout-readonly"}


@spec("FR-001")
def test_two_accounts_in_one_tree_fail(records: Records) -> None:
    other = "9" * 12
    files = _files(records)
    files["eks/access-policy.json"]["principalArn"] = f"arn:aws:iam::{other}:role/opscout-readonly"

    report = prove(Tree(files), records)

    assert "2 different accounts" in _messages(report, "placeholder")
