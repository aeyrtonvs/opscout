# SPDX-License-Identifier: Apache-2.0
"""Edge cases of the evaluator and the proofs (spec 010, FR-011, FR-012)."""

import copy
from dataclasses import replace
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import (
    Analysis,
    CannotProveError,
    GuardEntry,
    Identity,
    Records,
    Report,
    Tree,
    parse_capabilities,
    parse_guardrail,
    parse_policy,
)
from opscout.services.identity import prove

GUARDRAIL = "aws/guardrail.json"
CAPABILITIES = "aws/readonly/capabilities/"


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


@spec("FR-011")
def test_malformed_policies_and_records_are_refused() -> None:
    with pytest.raises(CannotProveError, match="must be an object"):
        parse_policy("x.json", {"Version": "2012-10-17", "Statement": [1]})
    with pytest.raises(CannotProveError, match="uses Extra"):
        parse_policy("x.json", {"Version": "2012-10-17", "Statement": [], "Extra": 1})
    with pytest.raises(ValueError, match="list"):
        parse_capabilities({})
    with pytest.raises(ValueError, match="object of groups"):
        parse_guardrail([])


@spec("FR-011")
def test_an_action_without_a_service_expands_to_nothing(records: Records) -> None:
    assert records.catalog.expand("ec2") == set()


@spec("FR-011")
def test_a_deny_in_the_boundary_bounds_nothing(records: Records) -> None:
    boundary = parse_policy(
        "cap",
        {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": "ec2:Describe*", "Resource": "*"},
                {"Effect": "Deny", "Action": "ec2:DescribeVpcs", "Resource": "*"},
            ],
        },
    )
    grant = parse_policy(
        "p",
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "ec2:*", "Resource": "*"}],
        },
    )
    analysis = Analysis(Identity("i", (grant,), boundary), records.catalog)

    assert analysis.denied_everywhere("ec2:describevpcs") == "cap#1"
    assert analysis.denied_everywhere("ec2:createtags") == "no allow in cap"


@spec("FR-012")
def test_a_tree_without_a_guardrail_is_named_and_exposed(records: Records) -> None:
    files = _files(records)
    del files[GUARDRAIL]

    report = prove(Tree(files), records)

    assert "aws/guardrail.json is missing" in _messages(report, "layout")
    assert "ssm:GetParameter " in _messages(report, "secret-allowed")


@spec("FR-012")
def test_a_resource_scoped_entry_left_open_is_named(records: Records) -> None:
    files = _files(records)
    files[GUARDRAIL]["Statement"] = [
        s for s in files[GUARDRAIL]["Statement"] if s.get("Sid") != "DenyApiKeyValues"
    ]

    report = prove(Tree(files), records)

    assert "apigateway:GET on arn:aws:apigateway:*::/apikeys" in _messages(report, "secret-allowed")


@spec("FR-012")
def test_a_guardrail_entry_outside_the_catalog_is_named(records: Records) -> None:
    extra = GuardEntry("secret-values", "nosuchservice:GetThing", "*", "a typo")

    report = prove(records.reference, replace(records, guardrail=(*records.guardrail, extra)))

    assert "guardrail entry nosuchservice:GetThing is not in the catalog" in _messages(
        report, "unknown-action"
    )


@spec("FR-012")
def test_an_unknown_capability_file_is_layout_only(records: Records) -> None:
    files = _files(records)
    files[f"{CAPABILITIES}extra.json"] = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "ec2:DescribeVpcs", "Resource": "*"}],
    }

    report = prove(Tree(files), records)

    assert {f.kind for f in report.findings} == {"layout"}


@spec("FR-012")
def test_a_deny_in_a_capability_is_allowed(records: Records) -> None:
    files = _files(records)
    files[f"{CAPABILITIES}cost.json"]["Statement"].append(
        {"Effect": "Deny", "Action": "ec2:CreateTags", "Resource": "*"}
    )

    assert prove(Tree(files), records).passed


@spec("FR-012")
def test_an_unknown_action_in_the_guardrail_is_named(records: Records) -> None:
    files = _files(records)
    files[GUARDRAIL]["Statement"][0]["Action"].append("ec2:NoSuchThing")

    report = prove(Tree(files), records)

    assert "ec2:NoSuchThing in aws/guardrail.json#DenySecretValues" in _messages(
        report, "unknown-action"
    )


@spec("FR-005")
def test_too_many_capability_files_exceed_the_attachment_limit(records: Records) -> None:
    files = _files(records)
    for index in range(20):
        files[f"{CAPABILITIES}extra-{index}.json"] = files[f"{CAPABILITIES}cost.json"]

    report = prove(Tree(files), records)

    assert "the read-only identity has 28 policies (limit 20)" in _messages(report, "too-large")


@spec("FR-012")
def test_an_empty_tree_names_what_is_missing(records: Records) -> None:
    report = prove(Tree({}), records)

    assert "Sizes: no AWS documents" in report.summary
    assert "Host identity: not part of this tree" in report.summary
    assert "aws/guardrail.json is missing" in _messages(report, "layout")


@spec("FR-013")
def test_an_added_key_in_a_host_document_is_named(records: Records) -> None:
    files = _files(records)
    files["ssm/opscout-ReadOnly-Memory.yaml"][0]["outputs"] = "extra"

    report = prove(Tree(files), records)

    assert _messages(report, "host-document") == (
        "ssm/opscout-ReadOnly-Memory.yaml differs from the reference at outputs"
    )


@spec("FR-009")
def test_a_catalog_document_the_host_identity_cannot_send_is_named(records: Records) -> None:
    files = _files(records)
    for path in ("aws/hosts/capability.json", "aws/hosts/boundary.json"):
        files[path]["Statement"][0]["Resource"] = [
            r for r in files[path]["Statement"][0]["Resource"] if not r.endswith("-Memory")
        ]

    report = prove(Tree(files), records)

    assert "ssm:SendCommand of opscout-ReadOnly-Memory on " in _messages(report, "read-missing")
