# SPDX-License-Identifier: Apache-2.0
"""Parsing policies and trees, failing closed (spec 010, FR-011; research R3)."""

from pathlib import Path
from typing import Any

import pytest

from opscout.adapters.identity_files import TreeError, read_tree
from opscout.core.identity import CannotProveError, parse_policy


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


def _policy(*statements: dict[str, Any], version: str = "2012-10-17") -> dict[str, Any]:
    return {"Version": version, "Statement": list(statements)}


ALLOW = {"Effect": "Allow", "Action": "logs:GetLogEvents", "Resource": "*"}


@spec("FR-011")
def test_a_policy_parses_with_a_list_or_a_single_statement() -> None:
    listed = parse_policy("a.json", _policy(ALLOW, {**ALLOW, "Sid": "Two", "Effect": "Deny"}))
    single = parse_policy("b.json", {"Version": "2012-10-17", "Statement": ALLOW})

    assert [s.ref for s in listed.statements] == ["a.json#0", "a.json#Two"]
    assert listed.statements[1].effect == "Deny"
    assert single.statements[0].actions == ("logs:GetLogEvents",)
    assert single.statements[0].resources == ("*",)


@spec("FR-011")
def test_not_action_not_resource_and_conditions_are_kept() -> None:
    statement = {
        "Effect": "Deny",
        "NotAction": ["ssm:SendCommand"],
        "NotResource": "arn:aws:ssm:*:123456789012:document/opscout-ReadOnly-*",
        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
    }
    parsed = parse_policy("g.json", _policy(statement)).statements[0]

    assert parsed.not_action
    assert parsed.not_resource
    assert parsed.conditional


@spec("FR-011")
@pytest.mark.parametrize(
    ("statement", "version", "message"),
    [
        ({**ALLOW, "Principal": "*"}, "2012-10-17", "Principal"),
        ({**ALLOW, "NotPrincipal": {"AWS": "*"}}, "2012-10-17", "NotPrincipal"),
        (ALLOW, "2008-10-17", "Version"),
        ({**ALLOW, "Extra": 1}, "2012-10-17", "Extra"),
        ({**ALLOW, "NotAction": "s3:*"}, "2012-10-17", "Action"),
        ({"Effect": "Allow", "Resource": "*"}, "2012-10-17", "Action"),
        ({"Effect": "Allow", "Action": "s3:*"}, "2012-10-17", "Resource"),
        ({**ALLOW, "Effect": "Maybe"}, "2012-10-17", "Effect"),
        ({**ALLOW, "Action": 3}, "2012-10-17", "Action"),
    ],
)
def test_what_cannot_be_proved_fails_closed(
    statement: dict[str, Any], version: str, message: str
) -> None:
    with pytest.raises(CannotProveError, match=message) as raised:
        parse_policy("x.json", _policy(statement, version=version))
    assert raised.value.ref.startswith("x.json")


@spec("FR-011")
def test_a_policy_without_statements_cannot_be_proved() -> None:
    with pytest.raises(CannotProveError, match="Statement"):
        parse_policy("x.json", {"Version": "2012-10-17"})
    with pytest.raises(CannotProveError, match="object"):
        parse_policy("x.json", ["not", "a", "policy"])


@spec("FR-011")
def test_a_broken_json_file_names_the_file_and_the_line(tmp_path: Path) -> None:
    (tmp_path / "aws").mkdir()
    (tmp_path / "aws" / "guardrail.json").write_text('{\n  "Version": \n}', encoding="utf-8")

    with pytest.raises(TreeError) as raised:
        read_tree(tmp_path)
    assert str(raised.value).startswith("aws/guardrail.json:3:")


@spec("FR-011")
def test_a_broken_yaml_file_names_the_file_and_the_line(tmp_path: Path) -> None:
    (tmp_path / "kubernetes").mkdir()
    (tmp_path / "kubernetes" / "view-binding.yaml").write_text(
        "kind: ClusterRoleBinding\nroleRef: [unclosed\n", encoding="utf-8"
    )

    with pytest.raises(TreeError) as raised:
        read_tree(tmp_path)
    assert str(raised.value).startswith("kubernetes/view-binding.yaml:")


@spec("FR-011")
def test_a_missing_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TreeError, match="no such directory"):
        read_tree(tmp_path / "absent")


@spec("FR-011")
def test_a_tree_holds_parsed_files_by_relative_path(tmp_path: Path) -> None:
    (tmp_path / "aws" / "readonly" / "capabilities").mkdir(parents=True)
    (tmp_path / "aws" / "readonly" / "capabilities" / "logs.json").write_text(
        '{"Version": "2012-10-17", "Statement": []}', encoding="utf-8"
    )
    (tmp_path / "ssm").mkdir()
    (tmp_path / "ssm" / "opscout-ReadOnly-Memory.yaml").write_text(
        "schemaVersion: '2.2'\n", encoding="utf-8"
    )
    (tmp_path / ".DS_Store").write_text("", encoding="utf-8")

    tree = read_tree(tmp_path)

    assert sorted(tree.files) == [
        "aws/readonly/capabilities/logs.json",
        "ssm/opscout-ReadOnly-Memory.yaml",
    ]
    assert tree.files["ssm/opscout-ReadOnly-Memory.yaml"] == [{"schemaVersion": "2.2"}]
