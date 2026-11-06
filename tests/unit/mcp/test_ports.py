# SPDX-License-Identifier: Apache-2.0
"""The AWS port's tables and environment helpers (spec 011, FR-007, FR-015)."""

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.aws import (
    RESOURCE_TYPES,
    SERVICE_PREFIX,
    client_for,
    find_environment,
    iam_action,
    region_for,
)
from opscout.core.config import Aws, AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

PROD = AwsEnvironment(
    name="example-prod",
    account_id="123456789012",
    profile="example-prod",
    regions=["us-east-1", "us-west-2"],
    aliases=["Production"],
)
AWS = Aws(environments=[PROD])


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-007")
def test_every_service_maps_to_a_catalog_prefix_and_back() -> None:
    catalog = load_records().catalog
    prefixes = {key.split(":", 1)[0] for key in catalog}
    for service, prefix in SERVICE_PREFIX.items():
        assert prefix in prefixes, service
        assert client_for(prefix) == service
    assert iam_action("elbv2", "DescribeTargetHealth") == (
        "elasticloadbalancing:DescribeTargetHealth"
    )
    assert iam_action("resourcegroupstaggingapi", "GetResources") == "tag:GetResources"
    with pytest.raises(KeyError):
        client_for("secretsmanager")


@spec("FR-015")
def test_an_environment_is_found_by_name_or_alias_and_its_region_checked() -> None:
    assert find_environment(AWS, "example-prod") is PROD
    assert find_environment(AWS, "production") is PROD
    assert region_for(PROD, None) == "us-east-1"
    assert region_for(PROD, "us-west-2") == "us-west-2"
    with pytest.raises(ToolError) as error:
        find_environment(AWS, "example-qa")
    assert error.value.reason is ErrorReason.UNKNOWN_ENVIRONMENT
    assert "example-prod" in error.value.message
    with pytest.raises(ToolError) as error:
        region_for(PROD, "eu-west-1")
    assert error.value.reason is ErrorReason.INVALID_INPUT
    with pytest.raises(ToolError) as error:
        find_environment(None, "example-prod")
    assert error.value.reason is ErrorReason.NOT_CONFIGURED
    assert "lambda-function" in RESOURCE_TYPES
