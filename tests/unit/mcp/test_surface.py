# SPDX-License-Identifier: Apache-2.0
"""The tool surface can only read (spec 011, FR-005, FR-006; SC-001).

Every action a tool declares must be in AWS's recorded catalog, must not be a write, and
must be allowed by the reference read-only identity, whose guardrail denies secret values,
credentials, reads that return plaintext secrets, application data and sessions.
"""

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Records
from opscout.core.tools import ToolSpec
from opscout.services.surface import SurfaceFinding, prove_surface
from opscout.services.tools.registry import REGISTRY


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


@spec("FR-006")
def test_every_declared_action_of_the_registry_is_a_proved_read(records: Records) -> None:
    assert prove_surface(REGISTRY, records) == []
    assert sum(len(tool.actions) for tool in REGISTRY) > 0


@spec("FR-006")
@pytest.mark.parametrize(
    ("action", "why"),
    [
        ("secretsmanager:GetSecretValue", "not allowed by the reference read-only identity"),
        ("lambda:GetFunctionConfiguration", "not allowed by the reference read-only identity"),
        ("ecs:DescribeTaskDefinition", "not allowed by the reference read-only identity"),
        ("ssm:StartSession", "a write"),
        ("ec2:CreateTags", "a write"),
        ("ec2:DescribeEverything", "not in the catalog"),
        ("cloudwatch:*", "a wildcard"),
        ("cloudwatch:Describe?larms", "a wildcard"),
    ],
)
def test_a_planted_tool_is_caught_and_named(records: Records, action: str, why: str) -> None:
    planted = ToolSpec("planted_tool", "A tool that should not exist.", frozenset({action}))

    findings = prove_surface((*REGISTRY, planted), records)

    assert len(findings) == 1
    (finding,) = findings
    assert (finding.tool, finding.action) == ("planted_tool", action)
    assert finding.reason.startswith(why)
    assert isinstance(finding, SurfaceFinding)


@spec("FR-005")
def test_a_tool_without_cloud_access_declares_nothing() -> None:
    for tool in REGISTRY:
        assert bool(tool.actions) == tool.needs_aws, tool.name
