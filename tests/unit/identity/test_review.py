# SPDX-License-Identifier: Apache-2.0
"""Faults found by the independent review fail the check (spec 010; T037).

Each test plants a change that an earlier version of the check passed: a narrowed
resource-scoped deny (H1), a wider command exception (H2), plaintext-secret reads reached
another way (H3), a service-prefix wildcard (M1), a hidden file (M2), duplicate keys (M3),
a system group (L1) and a type-changed value (L4).
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from opscout.adapters.identity_files import TreeError, export_tree, load_records, read_tree
from opscout.core.identity import (
    Analysis,
    CannotProveError,
    Records,
    Report,
    Tree,
    parse_policy,
    with_allow_all,
)
from opscout.services.identity import prove, readonly_identity

GUARDRAIL = "aws/guardrail.json"
HOSTS = ("aws/hosts/capability.json", "aws/hosts/boundary.json")


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _files(records: Records) -> dict[str, Any]:
    return copy.deepcopy(dict(records.reference.files))


def _messages(report: Report, kind: str) -> str:
    return "\n".join(f.message for f in report.findings if f.kind == kind)


def _statement(files: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in files[GUARDRAIL]["Statement"] if s.get("Sid") == sid)


@spec("FR-002")
@pytest.mark.parametrize(
    "resources",
    [
        ["arn:aws:apigateway:us-east-1::/apikeys", "arn:aws:apigateway:us-east-1::/apikeys/*"],
        ["arn:aws:apigateway:*::/apikeys", "arn:aws:apigateway:*::/apikeys/example"],
        ["arn:aws:apigateway:*::/apikeys", "arn:aws:apigateway:*::/apikeys/?"],
    ],
)
def test_a_narrowed_resource_deny_is_not_proof(records: Records, resources: list[str]) -> None:
    files = _files(records)
    _statement(files, "DenyApiKeyValues")["Resource"] = resources

    report = prove(Tree(files), records)

    assert "apigateway:GET on arn:aws:apigateway:*::/apikeys/*" in _messages(
        report, "secret-allowed"
    )


@spec("FR-009")
@pytest.mark.parametrize(
    "resource",
    [
        "arn:aws:ssm:*::document/AWS-RunRemoteScript",
        "arn:aws:ssm:*::document/AWS-RunDocument",
        "arn:aws:ssm:eu-west-1::document/AWS-RunShellScript",
        "arn:aws:ssm:*:*:document/opscout-ReadOnly-Disk",
        "arn:aws:ssm:*:123456789012:document/*",
        "arn:aws:ec2:*:*:instance/*",
    ],
)
def test_any_send_command_resource_outside_the_catalog_is_too_wide(
    records: Records, resource: str
) -> None:
    files = _files(records)
    files[GUARDRAIL]["Statement"] = [
        s for s in files[GUARDRAIL]["Statement"] if s.get("Sid") != "DenyOtherCommandDocuments"
    ]
    for path in HOSTS:
        files[path]["Statement"][0]["Resource"].append(resource)

    report = prove(Tree(files), records)

    assert resource in _messages(report, "exception-too-wide")


@spec("FR-009")
def test_send_command_through_not_resource_is_too_wide(records: Records) -> None:
    files = _files(records)
    for path in HOSTS:
        statement = files[path]["Statement"][0]
        statement["NotResource"] = ["arn:aws:ssm:*:123456789012:document/example"]
        del statement["Resource"]

    report = prove(Tree(files), records)

    assert "NotResource" in _messages(report, "exception-too-wide")


@spec("FR-002")
@pytest.mark.parametrize(
    "action",
    [
        "lambda:ListFunctions",
        "autoscaling:DescribeLaunchConfigurations",
        "sagemaker:DescribeModel",
        "codebuild:BatchGetBuilds",
        "batch:DescribeJobDefinitions",
        "lightsail:GetContainerServices",
        "apprunner:DescribeService",
        "amplify:GetBranch",
    ],
)
def test_reads_that_return_plaintext_secrets_are_denied(records: Records, action: str) -> None:
    analysis = Analysis(
        with_allow_all(readonly_identity(records.reference, records)), records.catalog
    )

    assert analysis.denied_everywhere(action.lower()) is not None
    configuration = next(c for c in records.capabilities if c.name == "configuration")
    assert action not in configuration.reads


@spec("FR-002")
def test_usage_plan_keys_are_denied(records: Records) -> None:
    files = _files(records)
    statement = _statement(files, "DenyApiKeyValues")
    statement["Resource"] = [r for r in statement["Resource"] if "usageplans" not in r]

    report = prove(Tree(files), records)

    assert "/usageplans/*/keys" in _messages(report, "secret-allowed")


@spec("FR-011")
@pytest.mark.parametrize("action", ["*:GetSecretValue", "secrets?anager:GetSecretValue"])
def test_a_wildcard_in_the_service_prefix_cannot_be_proved(action: str) -> None:
    policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Deny", "Action": [action], "Resource": "*"}],
    }

    with pytest.raises(CannotProveError, match="service prefix"):
        parse_policy("g.json", policy)


@spec("FR-012")
def test_a_hidden_file_under_the_documents_is_layout(tmp_path: Path, records: Records) -> None:
    export_tree(tmp_path)
    hidden = tmp_path / "aws" / "readonly" / "capabilities" / ".extra.json"
    hidden.write_text(
        '{"Version": "2012-10-17", "Statement": '
        '[{"Effect": "Allow", "Action": "*", "Resource": "*"}]}',
        encoding="utf-8",
    )
    (tmp_path / "aws" / ".DS_Store").write_text("", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("", encoding="utf-8")

    report = prove(read_tree(tmp_path), records)

    assert _messages(report, "layout") == (
        "aws/readonly/capabilities/.extra.json is not part of the identity"
    )


@spec("FR-011")
def test_duplicate_json_keys_are_refused(tmp_path: Path) -> None:
    (tmp_path / "aws").mkdir()
    (tmp_path / "aws" / "guardrail.json").write_text(
        '{"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Effect": "Allow", '
        '"Action": "*", "Resource": "*"}]}',
        encoding="utf-8",
    )

    with pytest.raises(TreeError, match=r"aws/guardrail\.json: duplicate key Effect"):
        read_tree(tmp_path)


@spec("FR-011")
def test_duplicate_yaml_keys_are_refused(tmp_path: Path) -> None:
    (tmp_path / "ssm").mkdir()
    (tmp_path / "ssm" / "opscout-ReadOnly-Memory.yaml").write_text(
        "runCommand: [cat /etc/shadow]\nrunCommand: [free -m]\n", encoding="utf-8"
    )

    with pytest.raises(TreeError, match=r"ssm/opscout-ReadOnly-Memory\.yaml:2: duplicate key"):
        read_tree(tmp_path)


@spec("FR-013")
@pytest.mark.parametrize("name", ["system:unauthenticated", "system:authenticated"])
def test_a_system_group_is_refused(records: Records, name: str) -> None:
    files = _files(records)
    files["kubernetes/view-binding.yaml"][0]["subjects"][0]["name"] = name

    report = prove(Tree(files), records)

    assert "system:" in _messages(report, "cluster")


@spec("FR-013")
def test_a_value_of_another_type_is_a_difference(records: Records) -> None:
    files = _files(records)
    document = files["ssm/opscout-ReadOnly-ServiceLog.yaml"][0]
    document["parameters"]["Lines"]["allowedValues"] = [50, 100, 200]

    report = prove(Tree(files), records)

    assert "parameters.Lines.allowedValues[0]" in _messages(report, "host-pattern")


@spec("FR-011")
def test_the_reference_exported_and_checked_still_passes(tmp_path: Path, records: Records) -> None:
    export_tree(tmp_path)

    report = prove(read_tree(tmp_path), records)

    assert report.passed, report.findings
    assert json.loads((tmp_path / GUARDRAIL).read_text(encoding="utf-8"))["Statement"]


@spec("FR-009")
def test_a_deny_in_the_host_documents_is_allowed(records: Records) -> None:
    files = _files(records)
    for path in HOSTS:
        files[path]["Statement"].append(
            {
                "Effect": "Deny",
                "Action": "ssm:SendCommand",
                "Resource": "arn:aws:ec2:*:*:instance/*",
            }
        )

    report = prove(Tree(files), records)

    assert "exception-too-wide" not in {f.kind for f in report.findings}
