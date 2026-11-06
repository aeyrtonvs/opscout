# SPDX-License-Identifier: Apache-2.0
"""The recorded action catalog and managed-policy copies (spec 010, FR-011; research R1, R2)."""

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Catalog


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@spec("FR-011")
def test_the_packaged_catalog_loads_with_its_source_and_date() -> None:
    catalog = load_records().catalog

    assert catalog.source == "https://servicereference.us-east-1.amazonaws.com/"
    assert catalog.fetched >= "2026-11-05"
    assert len(catalog.services) > 400
    assert len(catalog) > 20_000


@spec("FR-011")
@pytest.mark.parametrize(
    ("action", "write"),
    [
        ("ssm:SendCommand", True),
        ("athena:StartQueryExecution", True),
        ("logs:StartQuery", False),
        ("ce:GetCostAndUsage", False),
        ("sqs:ReceiveMessage", False),
        ("SSM:sendcommand", True),
    ],
)
def test_access_levels_match_the_verified_facts(action: str, write: bool) -> None:
    assert load_records().catalog.is_write(action) is write


@spec("FR-011")
def test_lookup_is_case_insensitive_and_unknown_actions_are_none() -> None:
    catalog = load_records().catalog

    assert catalog.name("LOGS:getlogevents") == "logs:GetLogEvents"
    assert catalog.flags("logs:NoSuchAction") is None
    assert catalog.name("nosuchservice:Get") is None


@spec("FR-011")
def test_patterns_expand_within_their_service_or_across_all() -> None:
    catalog = Catalog.from_data(
        {
            "source": "s",
            "fetched": "2026-11-05",
            "services": {
                "ec2": {"version": "v1", "actions": {"DescribeVpcs": "l", "CreateTags": "tw"}},
                "ecs": {"version": "v1", "actions": {"DescribeServices": ""}},
            },
        }
    )

    assert catalog.expand("ec2:Describe*") == {"ec2:describevpcs"}
    assert catalog.expand("ec?:Describe*") == {"ec2:describevpcs", "ecs:describeservices"}
    assert len(catalog.expand("*")) == 3
    assert catalog.expand("ec2:createtags") == {"ec2:createtags"}
    assert catalog.expand("ec2:Nope") == set()


@spec("FR-011")
def test_both_managed_copies_carry_arn_version_and_document() -> None:
    records = load_records()

    assert records.view_only.arn == "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
    assert records.read_only.arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    for managed in (records.view_only, records.read_only):
        assert managed.version.startswith("v")
        assert managed.fetched >= "2026-11-05"
        assert managed.policy.statements
