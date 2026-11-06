# SPDX-License-Identifier: Apache-2.0
"""The policy evaluator: exact and robust, sound by construction (spec 010, FR-011; R3)."""

from typing import Any

import pytest

from opscout.core.identity import (
    Analysis,
    Catalog,
    Identity,
    Policy,
    parse_policy,
    proves_allowed,
    proves_denied,
    with_allow_all,
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


def _policy(name: str, *statements: dict[str, Any]) -> Policy:
    return parse_policy(name, {"Version": "2012-10-17", "Statement": list(statements)})


def _allow(action: object, resource: object = "*", **extra: Any) -> dict[str, Any]:
    return {"Effect": "Allow", "Action": action, "Resource": resource, **extra}


def _deny(action: object, resource: object = "*", **extra: Any) -> dict[str, Any]:
    return {"Effect": "Deny", "Action": action, "Resource": resource, **extra}


ALL = _policy("all.json", _allow("*"))
CATALOG = Catalog.from_data(
    {
        "source": "s",
        "fetched": "2026-11-05",
        "services": {
            "ec2": {
                "version": "v1",
                "actions": {"DescribeVpcs": "l", "CreateTags": "tw", "RunInstances": "w"},
            },
            "secretsmanager": {"version": "v1", "actions": {"GetSecretValue": ""}},
            "ssm": {"version": "v1", "actions": {"SendCommand": "w"}},
        },
    }
)
DOC = "arn:aws:ssm:us-east-1:123456789012:document/opscout-ReadOnly-Disk"
SHELL = "arn:aws:ssm:us-east-1::document/AWS-RunShellScript"


@spec("FR-011")
def test_an_explicit_deny_beats_an_allow() -> None:
    identity = Identity("i", (_policy("p", _allow("ec2:*"), _deny("ec2:CreateTags")),), ALL)

    assert proves_allowed(identity, "ec2:DescribeVpcs", "*") == (True, None)
    assert proves_allowed(identity, "ec2:CreateTags", "*") == (False, "p#1")
    assert proves_denied(identity, "ec2:CreateTags", "*") == (True, "p#1")


@spec("FR-011")
def test_without_an_allow_the_request_is_denied_implicitly() -> None:
    identity = Identity("i", (_policy("p", _allow("ec2:DescribeVpcs")),), ALL)

    assert proves_allowed(identity, "ec2:CreateTags", "*") == (False, "no allow in i")
    assert proves_denied(identity, "ec2:CreateTags", "*") == (True, "no allow in i")


@spec("FR-011")
def test_an_allow_needs_the_boundary_too() -> None:
    boundary = _policy("cap", _allow("ec2:Describe*"))
    identity = Identity("i", (ALL,), boundary)

    assert proves_allowed(identity, "ec2:DescribeVpcs", "*") == (True, None)
    assert proves_allowed(identity, "ec2:CreateTags", "*") == (False, "no allow in cap")
    assert proves_denied(identity, "ec2:CreateTags", "*") == (True, "no allow in cap")


@spec("FR-011")
def test_action_wildcards_ignore_case_and_resource_wildcards_do_not() -> None:
    identity = Identity(
        "i",
        (_policy("p", _allow("EC2:describe?pcs", "arn:aws:ec2:*:123456789012:vpc/*")),),
        ALL,
    )

    assert proves_allowed(identity, "ec2:DescribeVpcs", "arn:aws:ec2:eu-west-1:123456789012:vpc/v")[
        0
    ]
    assert not proves_allowed(
        identity, "ec2:DescribeVpcs", "arn:aws:EC2:eu-west-1:123456789012:vpc/v"
    )[0]


@spec("FR-011")
def test_not_action_and_not_resource_are_honoured() -> None:
    guard = _policy(
        "g",
        {"Effect": "Deny", "Action": "ssm:SendCommand", "NotResource": [DOC]},
        {"Effect": "Deny", "NotAction": ["ec2:Describe*", "ssm:SendCommand"], "Resource": "*"},
    )
    identity = Identity("i", (ALL, guard), ALL)

    assert proves_allowed(identity, "ssm:SendCommand", DOC) == (True, None)
    assert proves_denied(identity, "ssm:SendCommand", SHELL) == (True, "g#0")
    assert proves_denied(identity, "ec2:CreateTags", "*") == (True, "g#1")
    assert proves_allowed(identity, "ec2:DescribeVpcs", "*") == (True, None)


@spec("FR-011")
def test_send_command_is_two_requests_that_must_both_be_allowed() -> None:
    instance = "arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0"
    identity = Identity("i", (_policy("p", _allow("ssm:SendCommand", [DOC])),), ALL)

    assert proves_allowed(identity, "ssm:SendCommand", DOC, instance) == (False, "no allow in i")
    widened = Identity("i", (_policy("p", _allow("ssm:SendCommand", [DOC, instance])),), ALL)
    assert proves_allowed(widened, "ssm:SendCommand", DOC, instance) == (True, None)


@spec("FR-011")
def test_conditions_never_deny_and_always_may_allow() -> None:
    condition = {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
    conditional_deny = Identity(
        "i", (ALL, _policy("g", _deny("ec2:CreateTags", Condition=condition))), ALL
    )
    conditional_allow = Identity(
        "i", (_policy("p", _allow("ec2:CreateTags", Condition=condition)),), ALL
    )

    assert proves_denied(conditional_deny, "ec2:CreateTags", "*") == (False, "all.json#0")
    assert proves_allowed(conditional_deny, "ec2:CreateTags", "*") == (False, "g#0")
    assert proves_allowed(conditional_allow, "ec2:CreateTags", "*") == (False, "p#0")
    assert proves_denied(conditional_allow, "ec2:CreateTags", "*") == (False, "p#0")


@spec("FR-011")
def test_the_robust_analysis_adds_allow_all() -> None:
    identity = Identity("i", (_policy("p", _allow("ec2:DescribeVpcs")),), ALL)
    robust = with_allow_all(identity)

    assert proves_allowed(robust, "ec2:CreateTags", "*") == (True, None)
    assert robust.policies[-1].name == "Allow * (added)"


@spec("FR-011")
def test_an_action_is_denied_everywhere_only_by_an_unconditional_deny_on_all_or_the_boundary() -> (
    None
):
    guard = _policy(
        "g",
        _deny("secretsmanager:GetSecretValue"),
        _deny("ec2:RunInstances", "arn:aws:ec2:*:*:instance/*"),
        _deny("ec2:CreateTags", Condition={"Bool": {"aws:SecureTransport": "true"}}),
    )
    boundary = _policy("cap", _allow(["ec2:*", "secretsmanager:*"]))
    analysis = Analysis(with_allow_all(Identity("i", (guard,), boundary)), CATALOG)

    assert analysis.denied_everywhere("secretsmanager:getsecretvalue") == "g#0"
    assert analysis.denied_everywhere("ssm:sendcommand") == "no allow in cap"
    assert analysis.denied_everywhere("ec2:runinstances") is None
    assert analysis.denied_everywhere("ec2:createtags") is None
    assert analysis.may_allow("ec2:createtags") == "Allow * (added)#0"


@spec("FR-011")
def test_may_allow_without_the_added_allow() -> None:
    identity = Identity(
        "i", (_policy("p", _allow("ec2:Describe*")), _policy("g", _deny("ec2:DescribeVpcs"))), ALL
    )
    analysis = Analysis(identity, CATALOG)

    assert analysis.may_allow("ec2:describevpcs") is None
    assert analysis.may_allow("ec2:createtags") is None
    assert analysis.allowed_somewhere() == set()
    wide = Analysis(Identity("i", (_policy("p", _allow("ec2:*")),), ALL), CATALOG)
    assert wide.allowed_somewhere() == {"ec2:describevpcs", "ec2:createtags", "ec2:runinstances"}
