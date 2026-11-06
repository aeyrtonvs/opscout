# SPDX-License-Identifier: Apache-2.0
"""Planted faults fail the check, named (spec 010, FR-012, FR-020; US1 scenarios 2-6)."""

import copy
from dataclasses import replace
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Catalog, ManagedPolicy, Records, Report, Tree, parse_policy
from opscout.services.identity import prove

GUARDRAIL = "aws/guardrail.json"
COST = "aws/readonly/capabilities/cost.json"


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


def _without(files: dict[str, Any], sid: str) -> None:
    files[GUARDRAIL]["Statement"] = [
        s for s in files[GUARDRAIL]["Statement"] if s.get("Sid") != sid
    ]


@spec("FR-012")
def test_removing_the_secret_value_denies_names_the_actions(records: Records) -> None:
    files = _files(records)
    _without(files, "DenySecretValues")

    report = prove(Tree(files), records)

    assert "secret-allowed" in _kinds(report)
    named = _messages(report, "secret-allowed")
    assert "ssm:GetParameter " in named
    assert "ssm:GetParametersByPath " in named
    # The cap still denies what ReadOnlyAccess never allows: defense in depth.
    assert "secretsmanager:GetSecretValue" not in named
    assert "kms:Decrypt" not in named


@spec("FR-020")
def test_an_allow_all_file_keeps_the_deny_properties_and_fails_layout(records: Records) -> None:
    files = _files(records)
    files["aws/readonly/everything.json"] = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }

    report = prove(Tree(files), records)

    assert _kinds(report) == {"layout"}
    assert "aws/readonly/everything.json" in _messages(report, "layout")


@spec("FR-020")
def test_allow_all_inside_a_capability_is_an_undeclared_grant(records: Records) -> None:
    files = _files(records)
    files[COST]["Statement"].append({"Effect": "Allow", "Action": "*", "Resource": "*"})

    report = prove(Tree(files), records)

    assert "undeclared-grant" in _kinds(report)
    assert not _kinds(report) & {"secret-allowed", "write-allowed"}


@spec("FR-020")
def test_a_mutation_added_by_mistake_is_capped(records: Records) -> None:
    files = _files(records)
    files[COST]["Statement"].append(
        {"Effect": "Allow", "Action": "ec2:CreateTags", "Resource": "*"}
    )

    report = prove(Tree(files), records)

    assert "write-allowed" not in _kinds(report)
    assert "ec2:CreateTags" in _messages(report, "undeclared-grant")


@spec("FR-012")
def test_without_the_cap_writes_are_allowed(records: Records) -> None:
    allow_all = parse_policy(
        "ReadOnlyAccess",
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
        },
    )
    uncapped = replace(
        records, read_only=ManagedPolicy(records.read_only.arn, "v0", "2026-11-05", allow_all)
    )

    report = prove(records.reference, uncapped)

    assert "write-allowed" in _kinds(report)
    assert "ec2:CreateTags" in _messages(report, "write-allowed")


@spec("FR-020")
def test_a_new_write_action_is_denied_without_an_edit(records: Records) -> None:
    data: dict[str, Any] = {
        "source": records.catalog.source,
        "fetched": "2026-12-01",
        "services": {
            prefix: {"version": version, "actions": {}}
            for prefix, version in records.catalog.services.items()
        },
    }
    for key in records.catalog:
        name = records.catalog.name(key)
        assert name is not None
        prefix, action = name.split(":", 1)
        data["services"][prefix]["actions"][action] = records.catalog.flags(key)
    data["services"]["ec2"]["actions"]["CreateShinyThing"] = "w"

    report = prove(records.reference, replace(records, catalog=Catalog.from_data(data)))

    assert not _kinds(report) & {"secret-allowed", "write-allowed"}


@spec("FR-012")
def test_a_conditional_deny_proves_nothing(records: Records) -> None:
    files = _files(records)
    for statement in files[GUARDRAIL]["Statement"]:
        if statement.get("Sid") == "DenySecretValues":
            statement["Condition"] = {"Bool": {"aws:SecureTransport": "true"}}

    report = prove(Tree(files), records)

    assert "ssm:GetParameter " in _messages(report, "secret-allowed")


@spec("FR-012")
def test_a_principal_cannot_be_proved(records: Records) -> None:
    files = _files(records)
    files[GUARDRAIL]["Statement"][0]["Principal"] = "*"

    report = prove(Tree(files), records)

    assert "cannot-prove" in _kinds(report)
    assert "Principal" in _messages(report, "cannot-prove")
