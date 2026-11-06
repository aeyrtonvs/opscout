# SPDX-License-Identifier: Apache-2.0
"""The registry of tools and their declarations (spec 011, FR-003, FR-005, FR-008)."""

import builtins
from pathlib import Path
from typing import Any

import pytest

from opscout.core.config import Configuration
from opscout.services.config import parse_config
from opscout.services.tools.registry import HANDLERS, REGISTRY
from opscout.services.tools.runtime import ToolContext, run_tool
from tests.unit.mcp.fakes import FakeCallLog, FakeGateway

CONTRACT = {
    "list_environments": set(),
    "parse_alert": set(),
    "resolve_environment": set(),
    "read_alarm": {
        "cloudwatch:DescribeAlarms",
        "cloudwatch:DescribeAlarmHistory",
        "cloudwatch:GetMetricData",
    },
    "read_metric": {"cloudwatch:GetMetricData", "cloudwatch:ListMetrics"},
    "query_logs": {
        "logs:StartQuery",
        "logs:GetQueryResults",
        "logs:StopQuery",
        "logs:DescribeLogGroups",
    },
    "recent_changes": {
        "cloudtrail:LookupEvents",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "ecs:ListServiceDeployments",
        "autoscaling:DescribeScalingActivities",
        "rds:DescribeEvents",
    },
    "find_resources": {"tag:GetResources"},
    "describe_resource": {
        "ecs:DescribeServices",
        "ecs:ListClusters",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "ec2:DescribeInstances",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:DescribeListeners",
        "autoscaling:DescribeAutoScalingGroups",
        "cloudwatch:DescribeAlarms",
        "cloudformation:DescribeStackResources",
        "cloudformation:ListStackResources",
        "cloudformation:DescribeStacks",
    },
    # Spec 012 (research R15): the triage tools declare no AWS action.
    "begin_triage": set(),
    "check_verdict": set(),
    "record_agreement": set(),
    "show_evidence": set(),
    "search_iac": set(),
    "read_iac": set(),
}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-003")
def test_every_tool_has_a_description_and_a_handler() -> None:
    assert [tool.name for tool in REGISTRY] == list(CONTRACT)
    for tool in REGISTRY:
        assert len(tool.description) >= 40, tool.name
        assert tool.description.endswith("."), tool.name
        assert tool.name in HANDLERS
    assert set(HANDLERS) == set(CONTRACT)


@spec("FR-005")
def test_each_tool_declares_exactly_the_contracts_actions() -> None:
    for tool in REGISTRY:
        assert set(tool.actions) == CONTRACT[tool.name], tool.name


@pytest.fixture
def opened_for_writing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    real_open = builtins.open

    def recording_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            opened.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    monkeypatch.setattr(Path, "write_text", lambda *_a, **_k: opened.append("write_text"))
    return opened


def _config() -> Configuration:
    return parse_config(
        b"schema_version: 1\naws:\n  environments:\n    - name: example-prod\n"
        b"      account_id: '123456789012'\n      profile: example-prod\n"
        b"      regions: [us-east-1]\n",
        "config.yaml",
    )


@spec("FR-008")
def test_a_call_writes_nothing_but_its_call_log_line(opened_for_writing: list[str]) -> None:
    log = FakeCallLog()
    context = ToolContext(config_loader=_config, gateway_factory=FakeGateway, call_log=log)

    for tool in REGISTRY:
        run_tool(tool.name, {}, context)

    assert opened_for_writing == []
    assert [entry.tool for entry in log.entries] == list(CONTRACT)
